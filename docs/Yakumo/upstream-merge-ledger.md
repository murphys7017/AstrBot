# Upstream Merge Ledger

This document records upstream changes that were reviewed but not merged into this fork.
Keep appending to it when reviewing future upstream updates, so old merge decisions remain easy to revisit.

## How to Update

- Add a new dated section for each upstream review.
- Record the upstream ref or tag that was reviewed.
- Separate decisions into `Not Merged`, `Deferred`, and `Already Absorbed`.
- For each skipped item, include the reason and the condition that would make it worth revisiting.
- Prefer linking to commit hashes, PR numbers, or file paths when available.

## 2026-04-27 Upstream Review

Reviewed upstream: `upstream/master` at `67c7445d` (`v4.23.6`)

Local strategy:

- Preserve the local prompt and memory architecture as the source of truth.
- Absorb upstream fixes only when they can fit this architecture with small, isolated changes.
- Do not merge changes that delete or overwrite the local `ContentPack -> Selector -> Render -> ProviderRequest` flow.

Already absorbed locally:

- Version bump to `4.23.6`.
- Firecrawl web search configuration and main-agent tool injection.
- SSL context compatibility using system trust store plus certifi fallback.
- OpenAI-compatible provider fixes for empty assistant messages, streaming sanitization, reasoning empty-string handling, and DeepSeek v4 reasoning history.
- Tool-loop reasoning preservation for empty reasoning content.
- Chat token stats display alignment: cached input tokens are shown separately from uncached input tokens.
- Existing local coverage already includes several upstream fixes: upload filename path traversal protection, backup importer path traversal protection, T2I raw text rendering, IME Enter handling, MiniMax WAV output, OpenRouter reasoning key, rate-limit count zero handling, RegexFilter pattern support, Telegram media group error handling, sandbox image download delivery, and SendMessageToUser workspace-relative file resolution.

### Not Merged

#### Prompt, Memory, and Postprocess Removals

Upstream deletes or reverts large local systems under:

- `astrbot/core/prompt/**`
- `astrbot/core/memory/**`
- `astrbot/core/postprocess/**`
- prompt-extension registration in `astrbot/core/star/context.py`
- memory lifecycle registration in `astrbot/core/core_lifecycle.py`

Reason:

These files are part of the local prompt/memory/postprocess architecture. Taking the upstream deletion would remove local context collection, prompt rendering, selector integration, memory services, prompt extension hooks, and after-send postprocess hooks.

Revisit if:

Upstream later introduces an equivalent or better architecture that can preserve local behavior, or if this fork intentionally drops the local prompt/memory system.

#### `astrbot/core/astr_main_agent.py` Wholesale Merge

Reason:

The upstream version removes local prompt pipeline integration, including `collect_context_pack`, `PromptRenderEngine`, `prompt_selector`, apply-visible/shadow pipeline modes, prompt trace extras, cached image/file extraction hooks, scaffold-free conversation save, and KB retrieval cache usage.

Local action taken:

Only the Firecrawl tool hook was cherry-picked into the local implementation.

Revisit if:

There is a specific independent bug fix in this file that can be extracted without changing the local prompt pipeline.

#### `astrbot/core/pipeline/process_stage/method/agent_sub_stages/internal.py` Wholesale Merge

Reason:

The upstream version removes final prompt trace logging, removes clean conversation-save user message replacement, and drops `prompt_selector` from `MainAgentBuildConfig`. This conflicts with the local prompt audit and selector work.

Revisit if:

There is a narrow runtime bug fix that does not affect final prompt tracing, conversation persistence, or selector config propagation.

#### WebUI Inline Edit, Regenerate, and Thread Flow

Main affected areas:

- `astrbot/dashboard/routes/chat.py`
- `astrbot/dashboard/routes/live_chat.py`
- `dashboard/src/components/chat/Chat.vue`
- `dashboard/src/components/chat/ChatInput.vue`
- `dashboard/src/components/chat/MessageList.vue`
- `dashboard/src/composables/useMessages.ts`

Reason:

The upstream implementation is a large feature set around editing, regeneration, threads, checkpoint IDs, and WebUI history mutation. It conflicts with the local checkpoint/message format decisions and local attachment rendering work. A partial type-only compatibility fix was kept, but the feature itself was not merged.

Revisit if:

The fork decides to implement inline edit/regenerate/thread UX explicitly. At that point, design it against the local checkpoint and prompt pipeline semantics instead of taking the upstream patch wholesale.

#### ChatPoint / Checkpoint Formatting-Only Diff

Main affected areas:

- `astrbot/core/agent/message.py`
- `tests/test_conversation_checkpoint.py`

Reason:

The remaining upstream diff is mostly formatting or test-only churn around checkpoint message dumping. It does not provide enough behavior value to justify merging over local checkpoint semantics.

Revisit if:

Future upstream checkpoint work fixes a real behavior bug or adds a compatible checkpoint API.

#### Dependency Removals

Main affected file:

- `pyproject.toml`

Reason:

Upstream removes dependencies that are still relevant to this fork, including local provider and media features. Local policy for this review was to keep dependency declarations unchanged except for the version bump.

Revisit if:

A dependency is proven unused in this fork after checking provider registration, media/TTS/STT paths, and optional feature gates.

#### Volcengine Ark Provider Removal

Main affected areas:

- `astrbot/core/provider/sources/volcengine_ark_source.py`
- provider config defaults and dashboard provider-source mapping

Reason:

This fork keeps the Volcengine Ark compatibility work. Upstream removes the provider path, which would be a feature regression locally.

Revisit if:

The provider is replaced by a cleaner OpenAI-compatible path that fully covers local Doubao/Volcengine image and request-format behavior.

#### QQ Official Message-Level Markdown Control

Main affected areas:

- `astrbot/core/message/message_event_result.py`
- `astrbot/core/pipeline/respond/stage.py`
- `astrbot/core/platform/sources/qqofficial/qqofficial_message_event.py`

Reason:

This is a useful platform feature, but it touches message chain semantics and respond-stage behavior. The local respond stage also includes postprocess dispatch, so this should not be merged opportunistically.

Revisit if:

There is a platform-specific need for per-message markdown control. Merge as a dedicated feature with tests covering postprocess hooks and non-QQ platform behavior.

#### KOOK Role Mention Support

Main affected areas:

- `astrbot/core/platform/sources/kook/**`
- `tests/test_kook/**`

Reason:

The feature is large and platform-specific. It is potentially valuable, but it requires a dedicated KOOK adapter review and test run because it changes role caching, event parsing, message conversion, and test fixtures.

Revisit if:

KOOK role mention support is needed by users of this fork. Merge as an isolated platform feature.

#### Knowledge Base FTS5 and EPUB Support

Main affected areas:

- `astrbot/core/db/vec_db/faiss_impl/document_storage.py`
- `astrbot/core/knowledge_base/retrieval/**`
- `astrbot/core/knowledge_base/parsers/**`
- dashboard knowledge-base upload UI

Reason:

Both are valuable knowledge-base features, but they touch retrieval/storage behavior and dependencies. They should be evaluated separately from prompt pipeline merging, especially because the fork already has local KB caching in prompt collection.

Revisit if:

Knowledge-base retrieval quality or EPUB upload support becomes a current priority. Merge with storage migration and retrieval tests.

#### `/stats` Command and WebUI Stats Feature Expansion

Main affected areas:

- `astrbot/builtin_stars/builtin_commands/commands/conversation.py`
- `astrbot/builtin_stars/builtin_commands/main.py`
- dashboard stats components and i18n

Reason:

Part of this feature already exists locally. The remaining upstream changes are useful but not urgent. The only small compatible display correction was absorbed.

Revisit if:

Conversation-level token usage command behavior needs to be aligned with upstream or exposed more clearly in the WebUI.

#### Clipboard Utility and Provider Config UI Refactors

Main affected areas:

- `dashboard/src/utils/clipboard.ts`
- provider-source UI composables and config UI files

Reason:

These are frontend quality-of-life refactors with conflict risk against local WebUI work. They are not required for the prompt/memory merge goal.

Revisit if:

The dashboard has copy-action bugs or provider config usability becomes a priority.

#### Test-Only and Fixture-Only Diffs

Examples:

- `tests/unit/test_upload_filename_sanitization.py`
- `tests/test_kook/data/kook_ws_event_group_message_with_mention.json`
- selected checkpoint and upload tests

Reason:

Some tests duplicate behavior already covered locally, while others depend on features intentionally not merged. They should not be added unless the corresponding behavior is merged.

Revisit if:

The related production code is merged or changed locally.
