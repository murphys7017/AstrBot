import { useModuleI18n } from '@/i18n/composables'
import { usePluginI18n } from '@/utils/pluginI18n'

export function useConfigTextResolver(props = {}) {
  const { tm, getRaw } = useModuleI18n('features/config-metadata')
  const { configText } = usePluginI18n()

  const translateIfKey = (value, fallback) => {
    if (!value || typeof value !== 'string') return fallback ?? value
    return getRaw(value) ? tm(value) : (fallback ?? value)
  }

  const hasPluginI18n = () => {
    return Boolean(
      props.pluginName
      && props.pluginI18n
      && Object.keys(props.pluginI18n).length > 0,
    )
  }

  const resolveConfigText = (path, attr, fallback) => {
    const fallbackText = translateIfKey(fallback) || ''
    if (!hasPluginI18n()) {
      return fallbackText
    }
    return configText(props.pluginI18n, path, attr, fallbackText)
  }

  const resolveConfigMetaText = (path, attr, metadata, fallback) => {
    const value = metadata?.[attr] ?? fallback
    const fallbackText = metadata?._i18n_fallback?.[attr] ?? fallback
    const translatedText = translateIfKey(value, fallbackText) || ''
    if (!hasPluginI18n()) {
      return translatedText
    }
    return configText(props.pluginI18n, path, attr, translatedText)
  }

  return {
    translateIfKey,
    resolveConfigText,
    resolveConfigMetaText,
  }
}
