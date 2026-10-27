<template>
  <div class="target-map-summary">
    <div class="target-map-chips">
      <span v-if="summaryEntries.length === 0" class="text-medium-emphasis">
        {{ emptyText }}
      </span>
      <v-chip
        v-for="([scope, target, kind]) in summaryEntries.slice(0, maxSummaryItems)"
        :key="scope"
        size="small"
        label
        variant="tonal"
      >
        {{ scope }}: {{ targetLabel(target, kind) }}
      </v-chip>
      <v-chip v-if="summaryEntries.length > maxSummaryItems" size="small" label>
        +{{ summaryEntries.length - maxSummaryItems }}
      </v-chip>
    </div>
    <v-btn
      size="small"
      color="primary"
      variant="tonal"
      prepend-icon="mdi-tune-variant"
      @click="openDialog"
    >
      {{ tm('runtimeTargetEditor.configure') }}
    </v-btn>
  </div>

  <v-dialog v-model="dialog" max-width="1040px" scrollable>
    <v-card class="target-map-dialog">
      <v-card-title class="target-map-dialog-header">
        <div>
          <div class="text-h6">{{ dialogTitle }}</div>
          <div class="text-body-2 text-medium-emphasis mt-1">
            {{ tm('runtimeTargetEditor.dialogSubtitle') }}
          </div>
        </div>
        <v-btn
          icon="mdi-close"
          variant="text"
          size="small"
          :aria-label="tm('runtimeTargetEditor.cancel')"
          @click="dialog = false"
        />
      </v-card-title>
      <v-divider />
      <v-card-text class="pa-4">
        <v-alert v-if="loadFailed" type="warning" variant="tonal" density="compact" class="mb-4">
          {{ tm('runtimeTargetEditor.loadFailed') }}
        </v-alert>
        <v-progress-linear v-if="loading" indeterminate color="primary" class="mb-4" />
        <v-alert type="info" variant="tonal" density="compact" class="mb-4">
          {{ tm('runtimeTargetEditor.promptExtensionPersonalHint') }}
        </v-alert>

        <div v-if="draftEntries.length === 0" class="text-medium-emphasis py-4 text-center">
          {{ emptyText }}
        </div>

        <div
          v-for="(entry, index) in draftEntries"
          :key="entry.id"
          class="target-map-entry"
        >
          <div class="target-map-entry-grid" :class="{ 'has-tool': entry.kind === 'tools' }">
            <v-combobox
              class="entry-plugin"
              v-model="entry.scope"
              :items="scopeOptions"
              item-title="title"
              item-value="value"
              :return-object="false"
              :label="tm('runtimeTargetEditor.pluginLabel')"
              :error-messages="entryError(index)"
              density="compact"
              variant="outlined"
              clearable
              hide-details="auto"
            />
            <v-select
              class="entry-kind"
              :model-value="entry.kind"
              @update:model-value="value => onKindChange(entry, value)"
              :items="kindOptions"
              :label="tm('runtimeTargetEditor.kindLabel')"
              density="compact"
              variant="outlined"
              hide-details
            />
            <v-combobox
              v-if="entry.kind === 'tools'"
              class="entry-tool"
              v-model="entry.tool"
              :items="toolOptions[entry.scope] || ['*']"
              :label="tm('runtimeTargetEditor.toolLabel')"
              density="compact"
              variant="outlined"
              :return-object="false"
              hide-details
            />
            <div class="entry-target">
              <div class="entry-target-label">
                {{ tm('runtimeTargetEditor.targetLabel') }}
              </div>
              <v-btn-toggle
                v-model="entry.target"
                mandatory
                divided
                color="primary"
                density="compact"
                class="target-map-target-toggle"
                :aria-label="tm('runtimeTargetEditor.targetLabel')"
              >
                <v-btn
                  v-for="option in targetOptionsFor(entry)"
                  :key="option.value"
                  :value="option.value"
                  size="small"
                >
                  {{ option.title }}
                </v-btn>
              </v-btn-toggle>
              <div v-if="targetError(index)" class="target-map-field-error">
                {{ targetError(index) }}
              </div>
            </div>
            <v-btn
              class="entry-remove"
              icon="mdi-delete-outline"
              color="error"
              variant="text"
              size="small"
              :aria-label="tm('runtimeTargetEditor.remove')"
              @click="removeEntry(index)"
            />
          </div>
        </div>

        <v-btn
          prepend-icon="mdi-plus"
          variant="tonal"
          color="primary"
          class="mt-3"
          @click="addEntry"
        >
          {{ tm('runtimeTargetEditor.add') }}
        </v-btn>
      </v-card-text>
      <v-card-actions class="pa-4">
        <v-spacer />
        <v-btn variant="text" @click="dialog = false">
          {{ tm('runtimeTargetEditor.cancel') }}
        </v-btn>
        <v-btn color="primary" :disabled="hasErrors" @click="saveEntries">
          {{ tm('runtimeTargetEditor.save') }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
import axios from 'axios'
import { computed, ref } from 'vue'
import { useModuleI18n } from '@/i18n/composables'

const props = defineProps({
  modelValue: {
    type: Object,
    default: () => ({})
  },
  maxSummaryItems: {
    type: Number,
    default: 3
  }
})

const emit = defineEmits(['update:modelValue'])
const { tm } = useModuleI18n('core.shared')
const dialog = ref(false)
const loading = ref(false)
const loadFailed = ref(false)
const draftEntries = ref([])
const scopeOptions = ref([])
const toolOptions = ref({})
let nextEntryId = 0

const validTargets = new Set(['core', 'personal_expression'])
const normalizedModelValue = computed(() => {
  if (!props.modelValue || Array.isArray(props.modelValue) || typeof props.modelValue !== 'object') {
    return {}
  }
  return props.modelValue
})
function bindingEntries(value) {
  return Object.entries(value).flatMap(([scope, binding]) => [
    ...(binding.llm_hooks ? [newEntry(scope, binding.llm_hooks, 'llm_hooks')] : []),
    ...(binding.prompt_extensions
      ? [newEntry(scope, binding.prompt_extensions, 'prompt_extensions')]
      : []),
    ...Object.entries(binding.tools || {}).map(
      ([tool, target]) => newEntry(scope, target, 'tools', tool)
    )
  ])
}
const summaryEntries = computed(() => bindingEntries(normalizedModelValue.value).map(
  entry => [
    `${entry.scope} / ${entry.kind === 'tools'
      ? entry.tool
      : entry.kind === 'prompt_extensions'
        ? tm('runtimeTargetEditor.promptExtensions')
        : tm('runtimeTargetEditor.llmHooks')}`,
    entry.target,
    entry.kind
  ]
))
const emptyText = computed(() => tm('runtimeTargetEditor.capabilityEmpty'))
const dialogTitle = computed(() => tm('runtimeTargetEditor.capabilityTitle'))
const kindOptions = computed(() => [
  { title: tm('runtimeTargetEditor.llmHooks'), value: 'llm_hooks' },
  { title: tm('runtimeTargetEditor.promptExtensions'), value: 'prompt_extensions' },
  { title: tm('runtimeTargetEditor.functionTools'), value: 'tools' }
])
const hasErrors = computed(() => draftEntries.value.some((_, index) => (
  Boolean(entryError(index)) || Boolean(targetError(index))
)))

function targetLabel(target, kind) {
  if (target === 'core') {
    return kind === 'prompt_extensions'
      ? tm('runtimeTargetEditor.targetCorePrompt')
      : tm('runtimeTargetEditor.targetCore')
  }
  if (target === 'personal_expression' || target === 'persona') {
    return kind === 'prompt_extensions'
      ? tm('runtimeTargetEditor.targetPersonaPrompt')
      : tm('runtimeTargetEditor.targetPersona')
  }
  return String(target || '')
}

function newEntry(scope = '', target = 'persona', kind = 'prompt_extensions', tool = '*') {
  nextEntryId += 1
  return {
    id: nextEntryId,
    scope,
    target,
    kind,
    tool
  }
}

function targetOptionsFor(entry) {
  const promptExtension = entry.kind === 'prompt_extensions'
  return [
    {
      title: tm(promptExtension
        ? 'runtimeTargetEditor.targetCorePrompt'
        : 'runtimeTargetEditor.targetCore'),
      value: 'core'
    },
    {
      title: tm(promptExtension
        ? 'runtimeTargetEditor.targetPersonaPrompt'
        : 'runtimeTargetEditor.targetPersona'),
      value: promptExtension ? 'persona' : 'personal_expression'
    }
  ]
}

function onKindChange(entry, kind) {
  entry.kind = kind
  if (kind === 'prompt_extensions' && entry.target === 'personal_expression') {
    entry.target = 'persona'
  } else if (kind !== 'prompt_extensions' && entry.target === 'persona') {
    entry.target = 'personal_expression'
  }
}

function entryError(index) {
  const scope = String(draftEntries.value[index]?.scope || '').trim()
  const { kind, tool } = draftEntries.value[index]
  if (!scope || (kind === 'tools' && !String(tool || '').trim())) {
    return tm('runtimeTargetEditor.scopeRequired')
  }
  const duplicateCount = draftEntries.value.filter(
    entry => String(entry.scope || '').trim() === scope && entry.kind === kind &&
      (kind !== 'tools' || String(entry.tool || '').trim() === String(tool || '').trim())
  ).length
  if (duplicateCount > 1) {
    return tm('runtimeTargetEditor.scopeDuplicate')
  }
  return ''
}

function targetError(index) {
  const { kind, target } = draftEntries.value[index]
  const allowedTargets = kind === 'prompt_extensions'
    ? new Set(['core', 'persona'])
    : validTargets
  if (!allowedTargets.has(target)) {
    return tm('runtimeTargetEditor.targetInvalid')
  }
  return ''
}

async function openDialog() {
  draftEntries.value = bindingEntries(normalizedModelValue.value)
  dialog.value = true
  await loadScopeOptions()
}

async function loadScopeOptions() {
  loading.value = true
  loadFailed.value = false
  const requests = [axios.get('/api/plugin/get'), axios.get('/api/tools/list')]

  const results = await Promise.allSettled(requests)
  const options = new Map()
  const pluginResult = results[0]
  if (pluginResult.status === 'fulfilled' && pluginResult.value.data?.status === 'ok') {
    for (const plugin of pluginResult.value.data.data || []) {
      if (!plugin?.name) continue
      const displayName = plugin.display_name || plugin.name
      options.set(plugin.name, {
        title: displayName === plugin.name ? plugin.name : `${displayName} (${plugin.name})`,
        value: plugin.name
      })
    }
  } else {
    loadFailed.value = true
  }

  const toolResult = results[1]
  toolOptions.value = {}
  if (toolResult) {
    if (toolResult.status === 'fulfilled' && toolResult.value.data?.status === 'ok') {
      for (const tool of toolResult.value.data.data || []) {
        if (tool?.origin !== 'plugin' || !tool.origin_name || !tool.name) continue
        const names = toolOptions.value[tool.origin_name] ||= ['*']
        names.push(tool.name)
      }
    } else {
      loadFailed.value = true
    }
  }

  scopeOptions.value = [...options.values()].sort((a, b) => a.title.localeCompare(b.title))
  loading.value = false
}

function addEntry() {
  draftEntries.value.push(newEntry())
}

function removeEntry(index) {
  draftEntries.value.splice(index, 1)
}

function saveEntries() {
  if (hasErrors.value) return
  const value = {}
  for (const entry of draftEntries.value) {
    const binding = value[String(entry.scope).trim()] ||= {}
    if (entry.kind === 'llm_hooks') {
      binding.llm_hooks = entry.target
    } else if (entry.kind === 'prompt_extensions') {
      binding.prompt_extensions = entry.target
    } else {
      binding.tools ||= {}
      binding.tools[String(entry.tool).trim()] = entry.target
    }
  }
  emit('update:modelValue', value)
  dialog.value = false
}
</script>

<style scoped>
.target-map-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.target-map-chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.target-map-dialog-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px;
  white-space: normal;
}

.target-map-entry {
  padding: 12px;
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  border-radius: 6px;
}

.target-map-entry + .target-map-entry {
  margin-top: 10px;
}

.target-map-entry-grid {
  display: grid;
  grid-template-columns: minmax(190px, 1.2fr) minmax(150px, 0.8fr) minmax(270px, 1.4fr) 40px;
  align-items: start;
  gap: 10px;
}

.target-map-entry-grid.has-tool {
  grid-template-columns: minmax(180px, 1.1fr) minmax(145px, 0.8fr) minmax(150px, 0.9fr) minmax(270px, 1.4fr) 40px;
}

.entry-target {
  min-width: 0;
}

.entry-target-label {
  margin: 0 0 6px 2px;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 0.75rem;
  line-height: 1rem;
}

.target-map-target-toggle {
  display: flex;
  width: 100%;
  min-width: 0;
}

.target-map-target-toggle :deep(.v-btn) {
  flex: 1 1 0;
  min-width: 0;
  height: auto;
  min-height: 44px;
  padding: 6px 8px;
  text-transform: none;
  white-space: normal;
  line-height: 1.2;
}

.target-map-target-toggle :deep(.v-btn__content) {
  width: 100%;
  white-space: normal;
  overflow-wrap: anywhere;
  text-align: center;
}

.target-map-field-error {
  margin: 4px 0 0 12px;
  color: rgb(var(--v-theme-error));
  font-size: 0.75rem;
}

.entry-remove {
  margin-top: 4px;
}

@media (max-width: 960px) {
  .target-map-entry-grid,
  .target-map-entry-grid.has-tool {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 40px;
  }

  .entry-plugin {
    grid-column: 1;
  }

  .entry-kind {
    grid-column: 2;
  }

  .entry-tool,
  .entry-target {
    grid-column: 1 / 3;
  }

  .entry-remove {
    grid-column: 3;
    grid-row: 1 / span 4;
  }
}

@media (max-width: 600px) {
  .target-map-summary {
    align-items: flex-start;
    flex-direction: column;
  }

  .target-map-dialog-header {
    padding: 16px;
  }

  .target-map-entry-grid,
  .target-map-entry-grid.has-tool {
    grid-template-columns: minmax(0, 1fr) 40px;
  }

  .entry-plugin,
  .entry-kind,
  .entry-tool,
  .entry-target {
    grid-column: 1;
  }

  .entry-plugin {
    grid-row: 1;
  }

  .entry-kind {
    grid-row: 2;
  }

  .entry-tool {
    grid-row: 3;
  }

  .entry-target {
    grid-row: 4;
  }

  .entry-remove {
    grid-column: 2;
    grid-row: 1;
  }
}
</style>
