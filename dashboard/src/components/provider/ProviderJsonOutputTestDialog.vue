<template>
  <v-dialog
    :model-value="modelValue"
    max-width="900"
    :persistent="running"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <v-card class="json-test-dialog">
      <v-card-title class="d-flex align-center ga-2">
        <v-icon color="primary">mdi-code-json</v-icon>
        <span>{{ tm('models.jsonTestTitle') }}</span>
      </v-card-title>

      <v-card-text class="json-test-dialog__body d-flex flex-column ga-4">
        <div class="text-body-2">
          <div><strong>{{ tm('models.tooltips.providerId') }}:</strong> {{ provider?.id }}</div>
          <div><strong>{{ tm('models.tooltips.modelId') }}:</strong> {{ provider?.model }}</div>
        </div>

        <v-alert type="info" variant="tonal" density="compact">
          {{ tm('models.jsonTestWarning') }}
        </v-alert>

        <div>
          <div class="text-subtitle-2 mb-1">{{ tm('models.jsonTestModeLabel') }}</div>
          <v-radio-group v-model="mode" inline hide-details :disabled="running">
            <v-radio
              value="prompt_only"
              :label="tm('models.jsonTestModePromptOnly')"
            />
            <v-radio
              value="provider_native_json"
              :label="tm('models.jsonTestModeNative')"
              :disabled="!supportsNativeJsonMode"
            />
          </v-radio-group>
          <div class="text-caption text-medium-emphasis mt-1">
            {{
              supportsNativeJsonMode
                ? tm('models.jsonTestNativeModeHint')
                : tm('models.jsonTestNativeModeUnavailable')
            }}
          </div>
        </div>

        <v-textarea
          v-model="template"
          :label="tm('models.jsonTemplateLabel')"
          :hint="tm('models.jsonTemplateHint')"
          persistent-hint
          auto-grow
          rows="14"
          max-rows="24"
          maxlength="16000"
          counter
          :error-messages="templateError ? [templateError] : []"
          class="json-template-editor"
          spellcheck="false"
          :disabled="running"
        />

        <v-alert v-if="runError" type="error" variant="tonal" density="compact">
          {{ runError }}
        </v-alert>

        <v-card v-if="result" variant="tonal" class="json-test-evidence">
          <v-card-text class="d-flex flex-column ga-1">
            <div class="d-flex align-center justify-space-between flex-wrap ga-2">
              <strong>{{ tm('models.jsonTestEvidenceTitle') }}</strong>
              <v-btn size="small" variant="text" @click="copyEvidence">
                {{ copyState ? tm('models.jsonTestEvidenceCopied') : tm('models.jsonTestEvidenceCopy') }}
              </v-btn>
            </div>
            <div class="text-caption">
              {{ result.provider_id }} · {{ result.adapter_type }} · {{ result.model }}
            </div>
            <div class="text-caption">
              {{ tm('models.jsonTestEvidenceEndpoint') }}:
              {{
                result.endpoint_host
                  || tm(result.endpoint_configured
                    ? 'models.jsonTestEvidenceUnknownEndpoint'
                    : 'models.jsonTestEvidenceDefaultEndpoint')
              }}
              <span v-if="result.endpoint_fingerprint">· {{ result.endpoint_fingerprint }}</span>
            </div>
            <div class="text-caption">
              {{ tm('models.jsonTestEvidenceObservedAt') }}: {{ result.observed_at }}
            </div>
            <div class="text-caption">
              {{ tm('models.jsonTestEvidenceAssessment') }}:
              {{ tm(`models.jsonTestCapabilityAssessment.${result.capability_assessment}`) }}
              <span v-if="result.mean_latency_ms !== null">
                · {{ tm('models.jsonTestEvidenceMeanLatency') }}: {{ result.mean_latency_ms }} ms
                ({{ tm('models.jsonTestEvidenceMedianLatency') }}: {{ result.median_latency_ms }} ms)
              </span>
            </div>
            <div v-if="copyError" class="text-caption text-error">{{ copyError }}</div>
          </v-card-text>
        </v-card>

        <v-alert
          v-if="result?.status === 'unsupported_provider'"
          type="warning"
          variant="tonal"
          density="compact"
        >
          {{ tm('models.jsonTestNativeUnsupportedProvider') }}
        </v-alert>
        <v-alert
          v-else-if="result?.status === 'unsupported_endpoint'"
          type="warning"
          variant="tonal"
          density="compact"
        >
          <div>{{ tm('models.jsonTestNativeUnsupportedEndpoint') }}</div>
          <div v-if="result.detail" class="text-caption mt-1">{{ result.detail }}</div>
        </v-alert>
        <v-alert
          v-else-if="result?.status === 'request_error'"
          type="warning"
          variant="tonal"
          density="compact"
        >
          <div>{{ tm('models.jsonTestNativeProbeFailed') }}</div>
          <div v-if="result.detail" class="text-caption mt-1">{{ result.detail }}</div>
        </v-alert>

        <section v-if="result?.status === 'completed'" class="json-test-results">
          <div class="d-flex align-center justify-space-between flex-wrap ga-2 mb-2">
            <strong>{{ tm('models.jsonTestSummary', { passed: result.passed, total: result.total }) }}</strong>
            <v-chip :color="result.failed === 0 ? 'success' : 'warning'" size="small" variant="tonal">
              {{ result.failed === 0 ? tm('models.jsonTestAllPassed') : tm('models.jsonTestHasFailures') }}
            </v-chip>
          </div>

          <v-expansion-panels variant="accordion">
            <v-expansion-panel v-for="item in result.results" :key="item.index">
              <v-expansion-panel-title>
                <div class="d-flex align-center ga-3">
                  <v-icon :color="item.passed ? 'success' : 'error'">
                    {{ item.passed ? 'mdi-check-circle' : 'mdi-alert-circle' }}
                  </v-icon>
                  <span>{{ tm('models.jsonTestAttempt', { index: item.index }) }}</span>
                  <v-chip size="x-small" variant="tonal">
                    {{ item.latency_ms }} ms
                  </v-chip>
                  <span v-if="item.error" class="text-error text-caption">{{ item.error }}</span>
                </div>
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <pre class="json-test-output">{{ item.output || tm('models.jsonTestEmptyOutput') }}</pre>
                <div v-if="item.output_truncated" class="text-caption text-medium-emphasis mt-2">
                  {{ tm('models.jsonTestOutputTruncated') }}
                </div>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>
        </section>
      </v-card-text>

      <v-card-actions class="pa-4 pt-0">
        <v-btn variant="text" :disabled="running" @click="resetTemplate">
          {{ tm('models.jsonTestReset') }}
        </v-btn>
        <v-spacer />
        <v-btn variant="text" :disabled="running" @click="close">
          {{ tm('dialogs.config.cancel') }}
        </v-btn>
        <v-btn color="primary" :loading="running" :disabled="!canRun" @click="runTest">
          {{ running ? tm('models.jsonTestRunning') : tm('models.jsonTestRun') }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import axios from 'axios'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false
  },
  provider: {
    type: Object,
    default: null
  },
  tm: {
    type: Function,
    required: true
  }
})

const emit = defineEmits(['update:modelValue', 'testing-change'])

const defaultTemplate = {
  turn_action: 'reply',
  segments: [{
    speech: '啊……怎么会这样？',
    actions: ['lower_head'],
    thought: '这件事出乎意料，让我感到遗憾',
    tendency: {
      Joy: 0,
      Trust: 1,
      Fear: 2,
      Surprise: 8,
      Sadness: 7,
      Disgust: 0,
      Anger: 1,
      Anticipation: 0
    }
  }],
  effect_calls: []
}

const template = ref(JSON.stringify(defaultTemplate, null, 2))
const mode = ref('prompt_only')
const templateError = ref('')
const runError = ref('')
const running = ref(false)
const result = ref(null)
const copyState = ref(false)
const copyError = ref('')

const canRun = computed(() => {
  return !running.value && Boolean(props.provider?.id)
})
const supportsNativeJsonMode = computed(() => {
  return ['openai_chat_completion', 'googlegenai_chat_completion'].includes(
    props.provider?.type
  )
})

watch(
  () => [props.modelValue, props.provider?.id],
  ([isOpen]) => {
    if (isOpen) resetDialog()
  }
)

watch([template, mode], () => {
  result.value = null
  runError.value = ''
  templateError.value = ''
  copyState.value = false
  copyError.value = ''
})

function resetDialog() {
  template.value = JSON.stringify(defaultTemplate, null, 2)
  mode.value = 'prompt_only'
  templateError.value = ''
  runError.value = ''
  result.value = null
  copyState.value = false
  copyError.value = ''
}

function resetTemplate() {
  template.value = JSON.stringify(defaultTemplate, null, 2)
  templateError.value = ''
}

function close() {
  if (!running.value) emit('update:modelValue', false)
}

async function runTest() {
  templateError.value = ''
  runError.value = ''
  result.value = null
  copyState.value = false
  copyError.value = ''

  if (template.value.length > 16000) {
    templateError.value = props.tm('models.jsonTemplateTooLong')
    return
  }

  let parsedTemplate
  try {
    parsedTemplate = JSON.parse(template.value)
  } catch {
    templateError.value = props.tm('models.jsonTemplateInvalid')
    return
  }
  if (parsedTemplate === null || typeof parsedTemplate !== 'object' || Array.isArray(parsedTemplate)) {
    templateError.value = props.tm('models.jsonTemplateInvalid')
    return
  }

  running.value = true
  emit('testing-change', props.provider.id, true)
  try {
    const response = await axios.post('/api/config/provider/test_json_output', {
      provider_id: props.provider.id,
      template: template.value,
      mode: mode.value
    })
    if (response.data?.status !== 'ok') {
      throw new Error(response.data?.message || props.tm('models.jsonTestFailed'))
    }
    result.value = response.data.data
  } catch (error) {
    runError.value = error.response?.data?.message || error.message || props.tm('models.jsonTestFailed')
  } finally {
    running.value = false
    emit('testing-change', props.provider.id, false)
  }
}

async function copyEvidence() {
  copyError.value = ''
  try {
    await navigator.clipboard.writeText(JSON.stringify(result.value, null, 2))
    copyState.value = true
  } catch {
    copyState.value = false
    copyError.value = props.tm('models.jsonTestEvidenceCopyFailed')
  }
}
</script>

<style scoped>
.json-template-editor :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
}

.json-test-dialog {
  display: flex;
  flex-direction: column;
  max-height: 90vh;
}

.json-test-dialog__body {
  min-height: 0;
  overflow-y: auto;
}

.json-test-results {
  min-height: 0;
}

.json-test-evidence {
  flex: 0 0 auto;
}

.json-test-output {
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  padding: 12px;
  border-radius: 8px;
  background: rgba(var(--v-theme-on-surface), 0.05);
  font-size: 12px;
}
</style>
