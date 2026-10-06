import { ref, computed } from 'vue';
import axios from 'axios';

export interface ChunkedUploadApi {
    initUpload(payload: { filename: string; total_size: number; content_type?: string }): Promise<any>;
    uploadChunk(payload: { upload_id: string; chunk_index: number; chunk: Blob }): Promise<any>;
    completeUpload(payload: { upload_id: string }): Promise<any>;
    abortUpload(payload: { upload_id: string }): Promise<any>;
    statusUpload(payload: { upload_id: string }): Promise<any>;
}

const CONCURRENT_UPLOADS = 5;
const CHUNK_MAX_ATTEMPTS = 3;

export function useChunkedUpload(api: ChunkedUploadApi) {
    const status = ref<'idle' | 'uploading' | 'error' | 'done'>('idle');
    const uploadedBytes = ref(0);
    const totalBytes = ref(0);
    const errorMessage = ref('');
    const percent = computed(() => totalBytes.value ? Math.round(uploadedBytes.value / totalBytes.value * 100) : 0);
    let file: File | null = null;
    let uploadId = '';
    let chunkSize = 0;
    let totalChunks = 0;
    let cancelled = false;

    const data = (response: any) => {
        if (response.data?.status !== 'ok') throw new Error(response.data?.message || 'Upload failed');
        return response.data.data;
    };

    async function uploadOne(index: number, sessionId: string) {
        const start = index * chunkSize;
        const chunk = file!.slice(start, Math.min(start + chunkSize, file!.size));
        let lastError: any;
        for (let attempt = 0; attempt < CHUNK_MAX_ATTEMPTS; attempt += 1) {
            if (cancelled) throw new Error('cancelled');
            try {
                data(await api.uploadChunk({ upload_id: sessionId, chunk_index: index, chunk }));
                uploadedBytes.value += chunk.size;
                return;
            } catch (error) {
                lastError = error;
            }
        }
        throw lastError;
    }

    async function runPool(indexes: number[], sessionId: string) {
        const pending = [...indexes];
        const active: Promise<void>[] = [];
        while (!cancelled && (pending.length || active.length)) {
            while (pending.length && active.length < CONCURRENT_UPLOADS) {
                const index = pending.shift()!;
                const promise = uploadOne(index, sessionId).finally(() => {
                    const position = active.indexOf(promise);
                    if (position >= 0) active.splice(position, 1);
                });
                active.push(promise);
            }
            if (active.length) await Promise.race(active);
        }
        if (cancelled) throw new Error('cancelled');
    }

    async function start(input: File) {
        file = input;
        cancelled = false;
        status.value = 'uploading';
        errorMessage.value = '';
        totalBytes.value = input.size;
        try {
            const init = data(await api.initUpload({ filename: input.name, total_size: input.size, content_type: input.type }));
            uploadId = init.upload_id;
            chunkSize = init.chunk_size;
            totalChunks = init.total_chunks;
            uploadedBytes.value = 0;
            await runPool(Array.from({ length: totalChunks }, (_, index) => index), uploadId);
            const result = data(await api.completeUpload({ upload_id: uploadId }));
            status.value = 'done';
            return result;
        } catch (error: any) {
            if (cancelled) return undefined;
            status.value = 'error';
            errorMessage.value = error?.response?.data?.message || error?.message || 'Upload failed';
            return undefined;
        }
    }

    async function resume() {
        if (!file) return undefined;
        cancelled = false;
        status.value = 'uploading';
        try {
            let received: number[] = [];
            try {
                const state = data(await api.statusUpload({ upload_id: uploadId }));
                received = state.received_chunks || [];
            } catch {
                uploadId = '';
            }
            if (!uploadId) {
                const init = data(await api.initUpload({ filename: file.name, total_size: file.size, content_type: file.type }));
                uploadId = init.upload_id;
                chunkSize = init.chunk_size;
                totalChunks = init.total_chunks;
                received = [];
            }
            uploadedBytes.value = received.reduce((total, index) => {
                const start = index * chunkSize;
                return total + Math.min(chunkSize, file!.size - start);
            }, 0);
            await runPool(Array.from({ length: totalChunks }, (_, index) => index).filter(index => !received.includes(index)), uploadId);
            const result = data(await api.completeUpload({ upload_id: uploadId }));
            status.value = 'done';
            return result;
        } catch (error: any) {
            status.value = 'error';
            errorMessage.value = error?.response?.data?.message || error?.message || 'Upload failed';
            return undefined;
        }
    }

    async function cancel() {
        cancelled = true;
        if (uploadId) await api.abortUpload({ upload_id: uploadId }).catch(() => undefined);
        reset();
    }

    function reset() {
        status.value = 'idle';
        uploadedBytes.value = 0;
        totalBytes.value = 0;
        errorMessage.value = '';
        file = null;
        uploadId = '';
        chunkSize = 0;
        totalChunks = 0;
    }

    return { status, percent, uploadedBytes, totalBytes, errorMessage, start, resume, cancel, reset };
}

export const chatChunkedUploadApi: ChunkedUploadApi = {
    initUpload: payload => axios.post('/api/chat/post_file/init', payload),
    uploadChunk: payload => {
        const form = new FormData();
        form.append('upload_id', payload.upload_id);
        form.append('chunk_index', String(payload.chunk_index));
        form.append('chunk', payload.chunk);
        return axios.post('/api/chat/post_file/chunk', form);
    },
    completeUpload: payload => axios.post('/api/chat/post_file/complete', payload),
    abortUpload: payload => axios.post('/api/chat/post_file/abort', payload),
    statusUpload: payload => axios.post('/api/chat/post_file/status', payload),
};
