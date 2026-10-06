// Locale modules are loaded only when the selected language is needed.
import type zhCN from "./locales/zh-CN";

export type Translations = typeof zhCN;

export const localeLoaders = {
  "zh-CN": () => import("./locales/zh-CN").then((module) => module.default),
  "en-US": () => import("./locales/en-US").then((module) => module.default),
  "ru-RU": () => import("./locales/ru-RU").then((module) => module.default),
  "ja-JP": () => import("./locales/ja-JP").then((module) => module.default),
} as const;

export type Locale = keyof typeof localeLoaders;
