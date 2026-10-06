import { ref, computed } from 'vue';
import axios from 'axios';

export interface ChunkedUploadApi {
    initUpload(payload: { filename: string; total_size: number; content_type?: string }): Promise<any>;
    uploadChunk(payload: { upload_id: string; chunk_index: number; chunk: Blob }): Promise<any>;
    completeUpload(payload: { upload_id: string }): Promise<any>;
    abortUpload(payload: { upload_id: string }): Promise<any>;
    statusUpload(payload: { upload_id: string }): Promise<any>;
}

export type ChunkedUploadStatus = 'idle' | 'uploading' | 'error' | 'done';
export type ChunkedUploadPhase = 'init' | 'chunks' | 'complete';

const CONCURRENT_UPLOADS = 5;
const CHUNK_MAX_ATTEMPTS = 3;
const CANCELLED_MESSAGE = 'cancelled';

export function useChunkedUpload(api: ChunkedUploadApi) {
    const status = ref<ChunkedUploadStatus>('idle');
    const phase = ref<ChunkedUploadPhase>('init');
    const uploadedBytes = ref(0);
    const totalBytes = ref(0);
    const errorMessage = ref('');
    const percent = computed(() => totalBytes.value ? Math.round(uploadedBytes.value / totalBytes.value * 100) : 0);
    const canResume = computed(() => status.value === 'error');

    let file: File | null = null;
    let uploadId = '';
    let chunkSize = 0;
    let totalChunks = 0;
    let chunkSizes: number[] = [];
    let cancelled = false;
    let runGeneration = 0;

    const data = (response: any) => {
        if (response.data?.status !== 'ok') throw new Error(response.data?.message || 'Upload failed');
        return response.data.data;
    };

    const cancelledError = () => new Error(CANCELLED_MESSAGE);
    const isCancelledError = (error: any) => error?.message === CANCELLED_MESSAGE;
    const isCurrent = (generation: number) => generation === runGeneration && !cancelled;

    function planChunks() {
        chunkSizes = [];
        for (let index = 0; index < totalChunks; index += 1) {
            const start = index * chunkSize;
            chunkSizes[index] = Math.max(0, Math.min(start + chunkSize, file!.size) - start);
        }
    }

    async function abortSession(sessionId: string) {
        if (!sessionId) return;
        try {
            await api.abortUpload({ upload_id: sessionId });
        } catch (error) {
            console.error('Failed to abort upload:', error);
        }
    }

    async function uploadOne(index: number, sessionId: string, generation: number) {
        const currentFile = file;
        const currentChunkSize = chunkSize;
        if (!currentFile || !currentChunkSize) throw cancelledError();

        const start = index * currentChunkSize;
        const chunk = currentFile.slice(start, Math.min(start + currentChunkSize, currentFile.size));
        let lastError: any;
        for (let attempt = 0; attempt < CHUNK_MAX_ATTEMPTS; attempt += 1) {
            if (!isCurrent(generation)) throw cancelledError();
            try {
                data(await api.uploadChunk({ upload_id: sessionId, chunk_index: index, chunk }));
                if (!isCurrent(generation)) throw cancelledError();
                uploadedBytes.value += chunk.size;
                return;
            } catch (error) {
                if (!isCurrent(generation) || isCancelledError(error)) throw cancelledError();
                lastError = error;
            }
        }
        throw lastError;
    }

    async function runPool(indexes: number[], sessionId: string, generation: number) {
        const pending = [...indexes];
        const active = new Set<Promise<void>>();
        let failure: any = null;

        while (!failure && isCurrent(generation) && (pending.length || active.size)) {
            while (pending.length && active.size < CONCURRENT_UPLOADS && isCurrent(generation)) {
                const index = pending.shift()!;
                const promise = uploadOne(index, sessionId, generation).finally(() => {
                    active.delete(promise);
                });
                active.add(promise);
            }
            if (active.size) {
                try {
                    await Promise.race(active);
                } catch (error) {
                    // Do not schedule more work after one chunk fails. Drain
                    // requests already sent so resume cannot race the old run.
                    failure = error;
                }
            }
        }

        if (active.size) await Promise.allSettled(active);
        if (!isCurrent(generation)) throw cancelledError();
        if (failure) throw failure;
    }

    async function initSession(generation: number) {
        const currentFile = file;
        if (!currentFile || !isCurrent(generation)) throw cancelledError();
        phase.value = 'init';
        const result = data(await api.initUpload({
            filename: currentFile.name,
            total_size: currentFile.size,
            content_type: currentFile.type,
        }));

        // A cancelled or superseded init may still have created a server
        // session. Abort that returned session without touching new state.
        if (!isCurrent(generation)) {
            void abortSession(result.upload_id);
            throw cancelledError();
        }

        uploadId = result.upload_id;
        chunkSize = result.chunk_size;
        totalChunks = result.total_chunks;
        planChunks();
        uploadedBytes.value = 0;
    }

    async function completeSession(sessionId: string, generation: number) {
        if (!isCurrent(generation)) throw cancelledError();
        phase.value = 'complete';
        const result = data(await api.completeUpload({ upload_id: sessionId }));
        if (!isCurrent(generation)) throw cancelledError();
        return result;
    }

    function clearState() {
        status.value = 'idle';
        phase.value = 'init';
        uploadedBytes.value = 0;
        totalBytes.value = 0;
        errorMessage.value = '';
        file = null;
        uploadId = '';
        chunkSize = 0;
        totalChunks = 0;
        chunkSizes = [];
    }

    function supersedeCurrentRun() {
        const previousSessionId = uploadId;
        cancelled = true;
        runGeneration += 1;
        if (previousSessionId) void abortSession(previousSessionId);
        uploadId = '';
        chunkSize = 0;
        totalChunks = 0;
        chunkSizes = [];
        uploadedBytes.value = 0;
        cancelled = false;
        return runGeneration;
    }

    function handleFailure(error: any, generation: number): undefined {
        if (generation !== runGeneration || cancelled || isCancelledError(error)) {
            if (generation === runGeneration && cancelled) {
                const sessionId = uploadId;
                clearState();
                if (sessionId) void abortSession(sessionId);
            }
            return undefined;
        }

        // A failed merge cannot safely be resumed against the same session.
        if (phase.value === 'complete') uploadId = '';
        status.value = 'error';
        errorMessage.value = error?.response?.data?.message || error?.message || 'Upload failed';
        return undefined;
    }

    async function start(input: File) {
        const generation = supersedeCurrentRun();
        file = input;
        status.value = 'uploading';
        errorMessage.value = '';
        totalBytes.value = input.size;
        try {
            await initSession(generation);
            phase.value = 'chunks';
            const sessionId = uploadId;
            await runPool(Array.from({ length: totalChunks }, (_, index) => index), sessionId, generation);
            const result = await completeSession(sessionId, generation);
            status.value = 'done';
            return result;
        } catch (error: any) {
            return handleFailure(error, generation);
        }
    }

    async function resume() {
        if (!file || status.value === 'uploading') return undefined;
        const generation = ++runGeneration;
        cancelled = false;
        status.value = 'uploading';
        errorMessage.value = '';
        try {
            let received: number[] = [];
            if (uploadId) {
                try {
                    const state = data(await api.statusUpload({ upload_id: uploadId }));
                    if (!isCurrent(generation)) throw cancelledError();
                    received = Array.isArray(state.received_chunks) ? state.received_chunks : [];
                    chunkSize = state.chunk_size || chunkSize;
                    totalChunks = state.total_chunks || totalChunks;
                    planChunks();
                } catch (error) {
                    if (!isCurrent(generation) || isCancelledError(error)) throw cancelledError();
                    uploadId = '';
                }
            }

            if (!uploadId) {
                await initSession(generation);
                received = [];
            } else {
                uploadedBytes.value = received.reduce((total, index) => total + (chunkSizes[index] || 0), 0);
            }

            phase.value = 'chunks';
            const missing = Array.from({ length: totalChunks }, (_, index) => index)
                .filter(index => !received.includes(index));
            const sessionId = uploadId;
            await runPool(missing, sessionId, generation);
            const result = await completeSession(sessionId, generation);
            status.value = 'done';
            return result;
        } catch (error: any) {
            return handleFailure(error, generation);
        }
    }

    async function cancel() {
        cancelled = true;
        runGeneration += 1;
        const sessionId = uploadId;
        clearState();
        if (sessionId) await abortSession(sessionId);
    }

    function reset() {
        cancelled = true;
        runGeneration += 1;
        const sessionId = uploadId;
        clearState();
        if (sessionId) void abortSession(sessionId);
    }

    return { status, phase, percent, uploadedBytes, totalBytes, errorMessage, canResume, start, resume, cancel, reset };
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
