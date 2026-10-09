<template>
  <v-alert
    class="chat-history-load-error"
    color="error"
    density="compact"
    variant="tonal"
  >
    <div class="chat-history-load-error__content">
      <span>{{ message }}</span>
      <v-btn
        :aria-label="retryLabel"
        :title="retryLabel"
        :loading="loading"
        :disabled="loading"
        icon="mdi-refresh"
        size="small"
        variant="text"
        @click="$emit('retry')"
      />
    </div>
  </v-alert>
</template>

<script setup lang="ts">
defineProps<{
  message: string;
  retryLabel: string;
  loading?: boolean;
}>();

defineEmits<{ retry: [] }>();
</script>

<style scoped>
.chat-history-load-error__content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  text-align: left;
}
</style>
