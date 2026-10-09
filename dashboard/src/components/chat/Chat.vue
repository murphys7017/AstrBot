<template>
  <div
    v-if="props.active"
    class="chat-ui"
    :class="{ 'is-dark': isDark, 'sidebar-collapsed': isSidebarCollapsed }"
  >
    <v-navigation-drawer
      v-model="chatSidebarDrawer"
      class="chat-sidebar"
      :class="{ collapsed: isSidebarCollapsed }"
      :permanent="lgAndUp"
      :temporary="!lgAndUp"
      :rail="lgAndUp && sidebarCollapsed"
      :width="280"
      :rail-width="68"
      location="left"
      floating
    >
      <div class="sidebar-top">
        <div v-if="lgAndUp" class="brand-row">
          <v-btn
            icon
            size="small"
            variant="text"
            class="sidebar-toggle"
            @click="sidebarCollapsed = !sidebarCollapsed"
          >
            <v-icon
              size="20"
              class="sidebar-action-icon"
              :class="{ 'chevron-collapsed': isSidebarCollapsed }"
            >
              mdi-chevron-left
            </v-icon>
          </v-btn>
        </div>

        <v-btn
          class="new-chat-btn sidebar-provider-btn"
          :class="{
            'icon-only': isSidebarCollapsed,
            'sidebar-workspace-btn--active': isProviderWorkspace,
          }"
          variant="text"
          :icon="isSidebarCollapsed"
          @click="openProviderWorkspace"
        >
          <v-icon
            size="20"
            class="sidebar-action-icon"
            :class="{ 'mr-2': !isSidebarCollapsed }"
            >mdi-creation</v-icon
          >
          <span v-if="!isSidebarCollapsed">{{ tm("actions.providerConfig") }}</span>
        </v-btn>

        <v-btn
          class="new-chat-btn"
          :class="{ 'icon-only': isSidebarCollapsed }"
          variant="text"
          :icon="isSidebarCollapsed"
          @click="startNewChat"
        >
          <v-icon
            size="20"
            class="sidebar-action-icon"
            :class="{ 'mr-2': !isSidebarCollapsed }"
            >mdi-square-edit-outline</v-icon
          >
          <span v-if="!isSidebarCollapsed">{{ tm("actions.newChat") }}</span>
        </v-btn>

        <ProjectList
          v-if="!isSidebarCollapsed"
          :projects="projects"
          :selected-project-id="selectedProjectId"
          @create-project="openCreateProjectDialog"
          @edit-project="openEditProjectDialog"
          @delete-project="handleDeleteProject"
          @select-project="selectProject"
        />
      </div>

      <div
        v-if="!isSidebarCollapsed"
        ref="sessionList"
        class="session-list"
        @scroll.passive="loadMoreSessions"
      >
        <div
          v-for="session in sidebarSessions"
          :key="session.session_id"
          class="session-item"
          :class="{ active: !isProviderWorkspace && currSessionId === session.session_id }"
          role="button"
          tabindex="0"
          @click="selectSession(session.session_id)"
          @keydown.enter="selectSession(session.session_id)"
          @keydown.space.prevent="selectSession(session.session_id)"
        >
          <span v-if="!isSidebarCollapsed" class="session-title">{{
            sessionTitle(session)
          }}</span>
          <div class="session-actions" @click.stop>
            <v-btn
              icon="mdi-pencil-outline"
              size="x-small"
              variant="text"
              class="session-action-btn"
              :title="tm('conversation.editDisplayName')"
              @click="editSidebarSessionTitle(session)"
            />
            <v-btn
              icon="mdi-delete-outline"
              size="x-small"
              variant="text"
              class="session-action-btn"
              :title="tm('actions.deleteChat')"
              @click="deleteSidebarSession(session)"
            />
          </div>
          <v-progress-circular
            v-if="isSessionRunning(session.session_id)"
            class="session-progress"
            indeterminate
            size="16"
            width="2"
          />
        </div>

        <div
          v-if="!sidebarSessions.length && !loadingSessions && !sessionsPagination.error"
          class="empty-sessions"
        >
          {{ tm("conversation.noHistory") }}
        </div>
        <v-progress-linear
          v-if="sessionsPagination.loading"
          color="primary"
          height="2"
          indeterminate
          :aria-label="tm('loading')"
        />
        <v-btn
          v-if="sessionsPagination.error"
          class="session-list-retry"
          size="small"
          variant="text"
          prepend-icon="mdi-refresh"
          @click="getSessions(sessionsPagination.append)"
        >
          {{ tm("conversation.retryLoading") }}
        </v-btn>
      </div>

      <div class="sidebar-footer">
        <StyledMenu
          location="top start"
          offset="10"
          :close-on-content-click="false"
        >
          <template #activator="{ props: menuProps }">
            <v-btn
              v-bind="menuProps"
              class="settings-btn"
              :class="{ 'icon-only': isSidebarCollapsed }"
              variant="text"
              :icon="isSidebarCollapsed"
            >
              <v-icon
                size="20"
                class="sidebar-action-icon"
                :class="{ 'mr-2': !isSidebarCollapsed }"
                >mdi-cog-outline</v-icon
              >
              <span v-if="!isSidebarCollapsed">{{
                t("core.common.settings")
              }}</span>
            </v-btn>
          </template>

          <div class="settings-menu-content">
            <v-menu
              location="end"
              offset="8"
              :open-on-hover="!isTouchDevice"
              :open-on-click="isTouchDevice"
              :close-on-content-click="true"
            >
              <template #activator="{ props: transportMenuProps }">
                <v-list-item
                  v-bind="transportMenuProps"
                  class="styled-menu-item"
                  rounded="md"
                >
                  <template #prepend>
                    <v-icon size="18">mdi-connection</v-icon>
                  </template>
                  <v-list-item-title>{{
                    tm("transport.title")
                  }}</v-list-item-title>
                  <template #append>
                    <span class="settings-menu-value">{{
                      currentTransportLabel
                    }}</span>
                    <v-icon size="18">mdi-chevron-right</v-icon>
                  </template>
                </v-list-item>
              </template>

              <v-card class="styled-menu-card" elevation="8" rounded="lg">
                <v-list density="compact" class="styled-menu-list pa-1">
                  <v-list-item
                    v-for="item in transportOptions"
                    :key="item.value"
                    class="styled-menu-item"
                    :class="{
                      'styled-menu-item-active': transportMode === item.value,
                    }"
                    rounded="md"
                    @click="transportMode = item.value"
                  >
                    <v-list-item-title>{{
                      tm(item.labelKey)
                    }}</v-list-item-title>
                    <template #append>
                      <v-icon v-if="transportMode === item.value" size="18">
                        mdi-check
                      </v-icon>
                    </template>
                  </v-list-item>
                </v-list>
              </v-card>
            </v-menu>

            <v-menu
              location="end"
              offset="8"
              :open-on-hover="!isTouchDevice"
              :open-on-click="isTouchDevice"
              :close-on-content-click="true"
            >
              <template #activator="{ props: languageMenuProps }">
                <v-list-item
                  v-bind="languageMenuProps"
                  class="styled-menu-item"
                  rounded="md"
                >
                  <template #prepend>
                    <v-icon size="18">mdi-translate</v-icon>
                  </template>
                  <v-list-item-title>{{
                    t("core.common.language")
                  }}</v-list-item-title>
                  <template #append>
                    <span class="settings-menu-value">{{
                      currentLanguage?.label || locale
                    }}</span>
                    <v-icon size="18">mdi-chevron-right</v-icon>
                  </template>
                </v-list-item>
              </template>

              <v-card class="styled-menu-card" elevation="8" rounded="lg">
                <v-list density="compact" class="styled-menu-list pa-1">
                  <v-list-item
                    v-for="lang in languageOptions"
                    :key="lang.value"
                    class="styled-menu-item"
                    :class="{
                      'styled-menu-item-active': locale === lang.value,
                    }"
                    rounded="md"
                    @click="switchLanguage(lang.value as Locale)"
                  >
                    <template #prepend>
                      <span class="language-flag">{{ lang.flag }}</span>
                    </template>
                    <v-list-item-title>{{ lang.label }}</v-list-item-title>
                    <template #append>
                      <v-icon v-if="locale === lang.value" size="18">
                        mdi-check
                      </v-icon>
                    </template>
                  </v-list-item>
                </v-list>
              </v-card>
            </v-menu>

            <v-list-item
              class="styled-menu-item"
              rounded="md"
              @click="toggleTheme"
            >
              <template #prepend>
                <v-icon size="18">{{
                  isDark ? "mdi-white-balance-sunny" : "mdi-weather-night"
                }}</v-icon>
              </template>
              <v-list-item-title>{{
                isDark ? tm("modes.lightMode") : tm("modes.darkMode")
              }}</v-list-item-title>
            </v-list-item>
          </div>
        </StyledMenu>
      </div>
    </v-navigation-drawer>

    <main
      class="chat-main"
      :class="{
        'empty-chat': !isProviderWorkspace &&
          !selectedProject && !loadingMessages && !activeMessages.length,
      }"
    >
      <section v-if="isProviderWorkspace" class="provider-workspace-shell">
        <ProviderChatCompletionPanel
          class="provider-workspace-page"
          :show-border="false"
        />
      </section>

      <ProjectView
        v-else-if="selectedProject"
        :project="selectedProject"
        :sessions="projectSessions"
        @select-session="selectProjectSession"
        @edit-session-title="editProjectSessionTitle"
        @delete-session="deleteProjectSession"
      >
        <section class="project-composer-shell">
          <ChatInput
            ref="inputRef"
            v-model:prompt="draft"
            :staged-images-url="stagedImagesUrl"
            :staged-audio-url="stagedAudioUrl"
            :staged-files="stagedNonImageFiles"
            :failed-uploads="failedUploadViews"
            :active-uploads="activeUploadViews"
            :disabled="sending"
            :enable-streaming="enableStreaming"
            :is-recording="isRecording"
            :is-running="
              Boolean(currSessionId && isSessionRunning(currSessionId))
            "
            :session-id="currSessionId || null"
            :current-session="currentSession"
            :reply-to="chatInputReplyTarget"
            :send-shortcut="sendShortcut"
            @send="sendCurrentMessage"
            @stop="stopCurrentSession"
            @toggle-streaming="toggleStreaming"
            @remove-image="removeImage"
            @remove-audio="removeAudio"
            @remove-file="removeFile"
            @retry-failed-upload="retryFailedUpload"
            @discard-failed-upload="discardFailedUpload"
            @cancel-active-upload="cancelActiveUpload"
            @start-recording="startRecording"
            @stop-recording="stopRecording"
            @paste-image="handlePaste"
            @file-select="handleFilesSelected"
            @clear-reply="replyTarget = null"
          />
        </section>
      </ProjectView>

      <template v-else>
        <section
          ref="messagesContainer"
          class="messages-panel"
          @scroll="handleMessagesScroll"
        >
          <v-progress-linear
            v-if="activeSessionPagination?.loading && activeMessages.length"
            class="history-loading"
            color="primary"
            height="2"
            indeterminate
            absolute
            location="top"
            aria-hidden="true"
          />
          <div v-if="loadingMessages" class="center-state">
            <v-progress-circular indeterminate size="32" width="3" />
          </div>

          <div
            v-else-if="!activeMessages.length && activeSessionPagination?.error"
            class="welcome-state"
          >
            <ChatHistoryLoadError
              :message="tm('history.loadFailed')"
              :retry-label="tm('history.retry')"
              :loading="activeSessionPagination.loading"
              @retry="retryCurrentSessionLoad"
            />
          </div>

          <div v-else-if="sessionProject" class="session-project-breadcrumb">
            <span>{{ sessionProject.title }}</span>
            <v-icon size="16">mdi-chevron-right</v-icon>
            <span>{{ currentSessionTitle }}</span>
          </div>

          <div v-else-if="!activeMessages.length" class="welcome-state">
            <div class="welcome-title">{{ tm("welcome.title") }}</div>
          </div>

          <div
            v-if="!loadingMessages && activeMessages.length"
            class="messages-list-shell"
          >
            <ChatHistoryLoadError
              v-if="activeSessionPagination?.error"
              class="history-load-error"
              :message="tm('history.loadEarlierFailed')"
              :retry-label="tm('history.retry')"
              :loading="activeSessionPagination.loading"
              @retry="retryCurrentSessionLoad"
            />
            <ChatMessageList
              v-model:edit-draft="messageEditDraft"
              :messages="activeMessages"
              :is-dark="isDark"
              :is-streaming="
                Boolean(currSessionId && isSessionRunning(currSessionId))
              "
              :enable-edit="
                !Boolean(currSessionId && isSessionRunning(currSessionId))
              "
              enable-regenerate
              enable-thread-selection
              :manage-refs-sidebar="false"
              :editing-message-id="editingMessage?.id || null"
              :saving-edit="savingMessageEdit"
              @open-edit="openMessageEdit"
              @cancel-edit="cancelMessageEdit"
              @save-edit="saveMessageEdit"
              @regenerate="handleRegenerateMessage"
              @regenerate-with-model="handleRegenerateMessage"
              @select-bot-text="handleBotTextSelection"
              @open-thread="openThreadPanel"
              @open-reasoning="openReasoningPanel"
              @open-refs="openRefsSidebar"
            />
          </div>
        </section>

        <section class="composer-shell">
          <ChatInput
            ref="inputRef"
            v-model:prompt="draft"
            :staged-images-url="stagedImagesUrl"
            :staged-audio-url="stagedAudioUrl"
            :staged-files="stagedNonImageFiles"
            :failed-uploads="failedUploadViews"
            :active-uploads="activeUploadViews"
            :disabled="sending"
            :enable-streaming="enableStreaming"
            :is-recording="isRecording"
            :is-running="
              Boolean(currSessionId && isSessionRunning(currSessionId))
            "
            :session-id="currSessionId || null"
            :current-session="currentSession"
            :reply-to="chatInputReplyTarget"
            :send-shortcut="sendShortcut"
            @send="sendCurrentMessage"
            @stop="stopCurrentSession"
            @toggle-streaming="toggleStreaming"
            @remove-image="removeImage"
            @remove-audio="removeAudio"
            @remove-file="removeFile"
            @retry-failed-upload="retryFailedUpload"
            @discard-failed-upload="discardFailedUpload"
            @cancel-active-upload="cancelActiveUpload"
            @start-recording="startRecording"
            @stop-recording="stopRecording"
            @paste-image="handlePaste"
            @file-select="handleFilesSelected"
            @clear-reply="replyTarget = null"
          />
        </section>
      </template>
    </main>

    <div
      v-if="threadSelection.visible"
      class="thread-selection-action"
      :style="{
        left: `${threadSelection.left}px`,
        top: `${threadSelection.top}px`,
      }"
    >
      <button
        class="thread-selection-button"
        type="button"
        @click="createThreadFromSelection"
      >
        {{ tm("thread.askInThread") }}
      </button>
    </div>

    <ProjectDialog
      v-model="projectDialogOpen"
      :project="editingProject"
      @save="saveProject"
    />
    <v-dialog v-model="sessionTitleDialogOpen" max-width="420">
      <v-card>
        <v-card-title class="text-h6">
          {{ tm("conversation.editDisplayName") }}
        </v-card-title>
        <v-card-text>
          <v-text-field
            v-model="sessionTitleDraft"
            :label="tm('conversation.displayName')"
            variant="outlined"
            density="comfortable"
            hide-details
            autofocus
            @keydown.enter="saveSessionTitleDialog"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="sessionTitleDialogOpen = false">
            {{ t("core.common.cancel") }}
          </v-btn>
          <v-btn
            color="primary"
            :loading="savingSessionTitle"
            @click="saveSessionTitleDialog"
          >
            {{ t("core.common.save") }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    <ThreadPanel
      v-model="threadPanelOpen"
      :thread="activeThread"
      :is-dark="isDark"
      :deleting="deletingThread"
      :get-provider-selection="getSelectedProviderSelection"
      @delete="deleteThread"
    />
    <ReasoningSidebar
      v-model="reasoningPanelOpen"
      :parts="activeReasoningParts"
      :is-dark="isDark"
    />
    <RefsSidebar v-model="refsSidebarOpen" :refs="selectedRefs" />
  </div>
</template>

<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  provide,
  reactive,
  ref,
  watch,
} from "vue";
import { useRoute, useRouter } from "vue-router";
import { useDisplay } from "vuetify";
import axios from "axios";
import StyledMenu from "@/components/shared/StyledMenu.vue";
import ProjectDialog, {
  type ProjectFormData,
} from "@/components/chat/ProjectDialog.vue";
import ProjectList, { type Project } from "@/components/chat/ProjectList.vue";
import ProjectView from "@/components/chat/ProjectView.vue";
import ChatInput from "@/components/chat/ChatInput.vue";
import ChatHistoryLoadError from "@/components/chat/ChatHistoryLoadError.vue";
import ChatMessageList from "@/components/chat/ChatMessageList.vue";
import type { RegenerateModelSelection } from "@/components/chat/RegenerateMenu.vue";
import ReasoningSidebar from "@/components/chat/ReasoningSidebar.vue";
import ThreadPanel from "@/components/chat/ThreadPanel.vue";
import RefsSidebar from "@/components/chat/message_list_comps/RefsSidebar.vue";
import { useSessions, type Session } from "@/composables/useSessions";
import {
  messageBlocks as buildMessageBlocks,
  useMessages,
  type ChatRecord,
  type ChatThread,
  type MessagePart,
  type TransportMode,
} from "@/composables/useMessages";
import { useMediaHandling } from "@/composables/useMediaHandling";
import { useRecording } from "@/composables/useRecording";
import { useProjects } from "@/composables/useProjects";
import { useProviderModelSelection } from "@/composables/useProviderModelSelection";
import { useCustomizerStore } from "@/stores/customizer";
import ProviderChatCompletionPanel from "@/components/provider/ProviderChatCompletionPanel.vue";
import {
  useI18n,
  useLanguageSwitcher,
  useModuleI18n,
} from "@/i18n/composables";
import type { Locale } from "@/i18n/types";
import { askForConfirmation, useConfirmDialog } from "@/utils/confirmDialog";
import { useToast } from "@/utils/toast";
import { readChatDraft, writeChatDraft } from "@/utils/chatDraftStorage";

const props = withDefaults(defineProps<{ chatboxMode?: boolean; active?: boolean }>(), {
  chatboxMode: false,
  active: true,
});

const route = useRoute();
const router = useRouter();
const { lgAndUp } = useDisplay();
const customizer = useCustomizerStore();
const { t } = useI18n();
const { tm } = useModuleI18n("features/chat");
const {
  selectedProviderId: currentProviderId,
  selectedModelName: currentModelName,
  setSelection: setProviderSelection,
} = useProviderModelSelection();
const confirmDialog = useConfirmDialog();
const toast = useToast();
const { languageOptions, currentLanguage, switchLanguage, locale } =
  useLanguageSwitcher();
const {
  sessions,
  sessionsPagination,
  currSessionId,
  getSessions,
  newSession,
  newChat,
  deleteSession,
  updateSessionTitle,
} = useSessions(props.chatboxMode);
const {
  projects,
  selectedProjectId,
  getProjects,
  createProject,
  updateProject,
  deleteProject: deleteProjectById,
  addSessionToProject,
  getProjectSessions,
} = useProjects();

const {
  stagedFiles,
  stagedImagesUrl,
  stagedAudioUrl,
  stagedNonImageFiles,
  failedUploadViews,
  activeUploadViews,
  processAndUploadImage,
  processAndUploadFile,
  handlePaste,
  removeImage,
  removeAudio,
  removeFile,
  retryFailedUpload,
  discardFailedUpload,
  cancelActiveUpload,
  clearStaged,
  cleanupMediaCache,
} = useMediaHandling();

type WorkspaceView = "chat" | "providers";

const sidebarCollapsed = ref(false);
const activeWorkspace = ref<WorkspaceView>("chat");
const projectDialogOpen = ref(false);
const editingProject = ref<Project | null>(null);
const sessionTitleDialogOpen = ref(false);
const sessionTitleDraft = ref("");
const editingSessionTitleId = ref("");
const refreshProjectSessionsAfterTitleSave = ref(false);
const savingSessionTitle = ref(false);
const messageEditDraft = ref("");
const editingMessage = ref<ChatRecord | null>(null);
const savingMessageEdit = ref(false);
const projectSessions = ref<Session[]>([]);
const loadingSessions = ref(false);
const draftKey = computed(() =>
  selectedProjectId.value
    ? `project:${selectedProjectId.value}`
    : currSessionId.value || "new",
);
let activeDraftKey = draftKey.value;
let draftSaveTimer: number | null = null;
const draft = ref(readChatDraft(activeDraftKey));
const messagesContainer = ref<HTMLElement | null>(null);
const sessionList = ref<HTMLElement | null>(null);
const inputRef = ref<InstanceType<typeof ChatInput> | null>(null);
const shouldStickToBottom = ref(true);
const suppressAutoScroll = ref(false);
const LOAD_EARLIER_SCROLL_THRESHOLD = 120;
let historyLoadToken = 0;
const replyTarget = ref<ChatRecord | null>(null);
const threadPanelOpen = ref(false);
const activeThread = ref<ChatThread | null>(null);
const reasoningPanelOpen = ref(false);
const activeReasoningTarget = ref<{
  message: ChatRecord;
  blockIndex: number;
} | null>(null);
const deletingThread = ref(false);
const refsSidebarOpen = ref(false);
const selectedRefs = ref<Record<string, unknown> | null>(null);
const threadSelection = reactive<{
  visible: boolean;
  left: number;
  top: number;
  message: ChatRecord | null;
  selectedText: string;
}>({
  visible: false,
  left: 0,
  top: 0,
  message: null,
  selectedText: "",
});
const enableStreaming = ref(true);
const sendShortcut = ref<"enter" | "shift_enter">("enter");
const {
  isRecording,
  startRecording: startRecorder,
  stopRecording: stopRecorder,
} = useRecording();
const chatSidebarDrawer = computed({
  get: () => lgAndUp.value || customizer.chatSidebarOpen,
  set: (value: boolean) => {
    if (!lgAndUp.value) {
      customizer.SET_CHAT_SIDEBAR(value);
    }
  },
});
const isSidebarCollapsed = computed(() =>
  lgAndUp.value ? sidebarCollapsed.value : !customizer.chatSidebarOpen,
);
const isProviderWorkspace = computed(
  () => activeWorkspace.value === "providers",
);
const activeReasoningParts = computed<MessagePart[]>(() => {
  if (!activeReasoningTarget.value) return [];
  const blocks = buildMessageBlocks(
    activeReasoningTarget.value.message.content || { type: "bot", message: [] },
  );
  const block = blocks[activeReasoningTarget.value.blockIndex];
  return block?.kind === "thinking" ? block.parts : [];
});

watch(reasoningPanelOpen, (open) => {
  if (!open) {
    activeReasoningTarget.value = null;
  }
});

const {
  loadingMessages,
  sending,
  loadedSessions,
  sessionDetails,
  sessionProjects,
  activeMessages,
  paginationBySession,
  isSessionRunning,
  isUserMessage,
  messageParts,
  loadSessionMessages,
  loadEarlierMessages,
  createLocalExchange,
  sendMessageStream,
  editMessage,
  continueEditedMessage,
  regenerateMessage,
  stopSession,
} = useMessages({
  currentSessionId: currSessionId,
  onSessionsChanged: getSessions,
  onStreamUpdate: (sessionId) => {
    if (sessionId === currSessionId.value && shouldStickToBottom.value) {
      scrollToBottom();
    }
  },
});

const activeSessionPagination = computed(() =>
  currSessionId.value ? paginationBySession[currSessionId.value] : undefined,
);

watch(currSessionId, () => {
  historyLoadToken += 1;
  suppressAutoScroll.value = false;
});

const transportMode = ref<TransportMode>(
  (localStorage.getItem("chat.transportMode") as TransportMode) === "websocket"
    ? "websocket"
    : "sse",
);

const transportOptions: Array<{ value: TransportMode; labelKey: string }> = [
  { value: "sse", labelKey: "transport.sse" },
  { value: "websocket", labelKey: "transport.websocket" },
];
const currentTransportLabel = computed(() =>
  tm(
    transportOptions.find((item) => item.value === transportMode.value)
      ?.labelKey || "transport.sse",
  ),
);

watch(transportMode, (mode) => {
  localStorage.setItem("chat.transportMode", mode);
});

watch(draft, (value) => {
  if (draftSaveTimer !== null) window.clearTimeout(draftSaveTimer);
  const key = activeDraftKey;
  draftSaveTimer = window.setTimeout(() => {
    writeChatDraft(key, value);
    draftSaveTimer = null;
  }, 300);
}, { flush: "sync" });

watch(draftKey, (key) => {
  flushDraft();
  activeDraftKey = key;
  draft.value = readChatDraft(key);
});

function flushDraft() {
  if (draftSaveTimer !== null) {
    window.clearTimeout(draftSaveTimer);
    draftSaveTimer = null;
  }
  writeChatDraft(activeDraftKey, draft.value);
}

const isDark = computed(() => customizer.uiTheme === "PurpleThemeDark");
const canSend = computed(
  () =>
    Boolean(draft.value.trim() || stagedFiles.value.length) &&
    !sending.value &&
    activeUploadViews.value.length === 0,
);
const currentSession = computed(
  () =>
    sessions.value.find(
      (session) => session.session_id === currSessionId.value,
    ) ||
    projectSessions.value.find(
      (session) => session.session_id === currSessionId.value,
    ) ||
    sessionDetails[currSessionId.value] ||
    null,
);
const sessionProject = computed(() =>
  currSessionId.value ? sessionProjects[currSessionId.value] : null,
);
const sidebarSessions = computed(() => {
  const current = currentSession.value;
  if (
    current &&
    !sessionProject.value &&
    !sessions.value.some((session) => session.session_id === current.session_id)
  ) {
    return [current, ...sessions.value];
  }
  return sessions.value;
});
const currentSessionTitle = computed(() =>
  currentSession.value ? sessionTitle(currentSession.value) : "",
);
const selectedProject = computed(
  () =>
    projects.value.find(
      (project) => project.project_id === selectedProjectId.value,
    ) || null,
);
const chatInputReplyTarget = computed(() =>
  replyTarget.value?.id == null
    ? null
    : {
        messageId: replyTarget.value.id,
        selectedText: replyPreview(replyTarget.value.id, ""),
      },
);

const SESSION_PROVIDER_STORAGE_PREFIX = "chat.sessionProvider.";

function readSessionProviderSelection(sessionId: string) {
  try {
    const raw = localStorage.getItem(SESSION_PROVIDER_STORAGE_PREFIX + sessionId);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.providerId === "string" && parsed.providerId) {
      return {
        providerId: parsed.providerId,
        modelName: typeof parsed.modelName === "string" ? parsed.modelName : "",
      };
    }
  } catch {
    // Ignore corrupted or unavailable local storage entries.
  }
  return null;
}

function writeSessionProviderSelection(
  sessionId: string,
  selection: { providerId?: string; modelName?: string } | null | undefined,
) {
  if (!sessionId || !selection?.providerId) return;
  try {
    localStorage.setItem(
      SESSION_PROVIDER_STORAGE_PREFIX + sessionId,
      JSON.stringify({
        providerId: selection.providerId,
        modelName: selection.modelName || "",
      }),
    );
  } catch {
    // Session model persistence must not block chat flows.
  }
}

watch([currentProviderId, currentModelName], ([providerId, modelName]) => {
  if (!currSessionId.value || !providerId) return;
  writeSessionProviderSelection(currSessionId.value, { providerId, modelName });
});

provide("isDark", isDark);

const isTouchDevice = ref(false);
let pointerMediaQuery: MediaQueryList | undefined;
let sessionListResizeObserver: ResizeObserver | undefined;
let autoScrollFrame: number | null = null;

function syncTouchDevice() {
  isTouchDevice.value = pointerMediaQuery?.matches ?? false;
}

onMounted(async () => {
  window.addEventListener("beforeunload", flushDraft);
  if (typeof ResizeObserver !== "undefined") {
    sessionListResizeObserver = new ResizeObserver(loadMoreSessions);
    if (sessionList.value) sessionListResizeObserver.observe(sessionList.value);
  }

  if (typeof window.matchMedia === "function") {
    pointerMediaQuery = window.matchMedia("(pointer: coarse)");
    syncTouchDevice();
    pointerMediaQuery.addEventListener("change", syncTouchDevice);
  }

  loadingSessions.value = true;
  try {
    await Promise.all([getSessions(), getProjects()]);
    const routeSessionId = getRouteSessionId();
    if (routeSessionId === "models") {
      activeWorkspace.value = "providers";
    } else if (routeSessionId) {
      await selectSession(routeSessionId, false);
    }
  } finally {
    loadingSessions.value = false;
  }
});

onBeforeUnmount(() => {
  flushDraft();
  window.removeEventListener("beforeunload", flushDraft);
  pointerMediaQuery?.removeEventListener("change", syncTouchDevice);
  sessionListResizeObserver?.disconnect();
  if (autoScrollFrame !== null) {
    window.cancelAnimationFrame(autoScrollFrame);
    autoScrollFrame = null;
  }
  cleanupMediaCache();
});

watch(
  [sessions, () => sessionsPagination.loading, projects, isSidebarCollapsed],
  () => {
    void nextTick(loadMoreSessions);
  },
  { flush: "post" },
);

watch(
  sessionList,
  (element, previousElement) => {
    if (!sessionListResizeObserver) return;
    if (previousElement) sessionListResizeObserver.unobserve(previousElement);
    if (element) sessionListResizeObserver.observe(element);
  },
  { flush: "post" },
);

watch(
  () => route.params.conversationId,
  async () => {
    const routeSessionId = getRouteSessionId();
    if (routeSessionId === "models") {
      activeWorkspace.value = "providers";
      return;
    }
    if (routeSessionId && routeSessionId !== currSessionId.value) {
      showChatWorkspace();
      selectedProjectId.value = null;
      await selectSession(routeSessionId, false);
    } else if (!routeSessionId && currSessionId.value) {
      showChatWorkspace();
      currSessionId.value = "";
    }
  },
);

watch(activeMessages, () => {
  if (!suppressAutoScroll.value && shouldStickToBottom.value) {
    scrollToBottom();
  }
});

function getRouteSessionId() {
  const raw = route.params.conversationId;
  return Array.isArray(raw) ? raw[0] : raw || "";
}

function loadMoreSessions() {
  const container = sessionList.value;
  if (
    !container ||
    container.clientHeight === 0 ||
    !sessionsPagination.hasMore ||
    sessionsPagination.loading ||
    sessionsPagination.error
  ) {
    return;
  }

  if (container.scrollHeight - container.scrollTop - container.clientHeight <= 96) {
    void getSessions(true);
  }
}

function basePath() {
  return props.chatboxMode ? "/chatbox" : "/chat";
}

function closeMobileSidebar() {
  if (!lgAndUp.value) {
    customizer.SET_CHAT_SIDEBAR(false);
  }
}

function closeSecondaryPanels() {
  threadSelection.visible = false;
  threadPanelOpen.value = false;
  activeThread.value = null;
  reasoningPanelOpen.value = false;
  activeReasoningTarget.value = null;
  refsSidebarOpen.value = false;
  selectedRefs.value = null;
}

function showChatWorkspace() {
  activeWorkspace.value = "chat";
}

async function openProviderWorkspace() {
  closeSecondaryPanels();
  activeWorkspace.value = "providers";
  const targetPath = `${basePath()}/models`;
  if (route.path !== targetPath) {
    await router.push(targetPath);
  }
  closeMobileSidebar();
}

function sessionTitle(session: Session) {
  return session.display_name?.trim() || tm("conversation.newConversation");
}

async function startNewChat() {
  showChatWorkspace();
  selectedProjectId.value = null;
  replyTarget.value = null;
  newChat();
  closeMobileSidebar();
  await focusChatInput();
}

function openCreateProjectDialog() {
  editingProject.value = null;
  projectDialogOpen.value = true;
}

function openEditProjectDialog(project: Project) {
  editingProject.value = project;
  projectDialogOpen.value = true;
}

async function selectProject(projectId: string) {
  showChatWorkspace();
  selectedProjectId.value = projectId;
  currSessionId.value = "";
  replyTarget.value = null;
  await router.push(basePath());
  await loadProjectSessions(projectId);
  closeMobileSidebar();
}

async function loadProjectSessions(projectId = selectedProjectId.value) {
  if (!projectId) {
    projectSessions.value = [];
    return;
  }
  projectSessions.value = await getProjectSessions(projectId);
}

async function handleDeleteProject(projectId: string) {
  await deleteProjectById(projectId);
  if (selectedProjectId.value === projectId) {
    selectedProjectId.value = null;
    projectSessions.value = [];
  }
}

function openSessionTitleDialog(
  sessionId: string,
  title: string,
  refreshProjectSessions = false,
) {
  editingSessionTitleId.value = sessionId;
  sessionTitleDraft.value = title;
  refreshProjectSessionsAfterTitleSave.value = refreshProjectSessions;
  sessionTitleDialogOpen.value = true;
}

async function saveSessionTitleDialog() {
  if (!editingSessionTitleId.value) return;

  savingSessionTitle.value = true;
  try {
    const sessionId = editingSessionTitleId.value;
    const displayName = sessionTitleDraft.value.trim();
    await axios.post("/api/chat/update_session_display_name", {
      session_id: sessionId,
      display_name: displayName,
    });
    updateSessionTitle(sessionId, displayName);
    if (sessionDetails[sessionId]) {
      sessionDetails[sessionId].display_name = displayName;
    }
    const projectSession = projectSessions.value.find(
      (session) => session.session_id === sessionId,
    );
    if (projectSession) {
      projectSession.display_name = displayName;
    }
    if (refreshProjectSessionsAfterTitleSave.value) {
      await loadProjectSessions();
    }
    sessionTitleDialogOpen.value = false;
  } finally {
    savingSessionTitle.value = false;
  }
}

function editSidebarSessionTitle(session: Session) {
  openSessionTitleDialog(session.session_id, session.display_name || "");
}

async function deleteSidebarSession(session: Session) {
  const title = sessionTitle(session);
  const message = tm("conversation.confirmDelete", { name: title });
  if (!(await askForConfirmation(message, confirmDialog))) return;

  const wasCurrent = currSessionId.value === session.session_id;
  await deleteSession(session.session_id);
  if (wasCurrent) {
    selectedProjectId.value = null;
    await router.push(basePath());
  }
}

async function selectProjectSession(sessionId: string) {
  selectedProjectId.value = null;
  await selectSession(sessionId);
}

async function editProjectSessionTitle(sessionId: string, title: string) {
  openSessionTitleDialog(sessionId, title, true);
}

async function deleteProjectSession(sessionId: string) {
  await deleteSession(sessionId);
  await loadProjectSessions();
}

async function saveProject(formData: ProjectFormData, projectId?: string) {
  if (projectId) {
    await updateProject(projectId, formData);
    return;
  }

  await createProject(formData);
}

async function selectSession(sessionId: string, pushRoute = true) {
  showChatWorkspace();
  selectedProjectId.value = null;
  currSessionId.value = sessionId;
  replyTarget.value = null;
  if (pushRoute && route.path !== `${basePath()}/${sessionId}`) {
    await router.push(`${basePath()}/${sessionId}`);
    if (currSessionId.value !== sessionId) return;
  }
  if (!loadedSessions[sessionId]) {
    await loadSessionMessages(sessionId);
    if (currSessionId.value !== sessionId) return;
  }
  const storedSelection = readSessionProviderSelection(sessionId);
  if (storedSelection) {
    setProviderSelection(storedSelection.providerId, storedSelection.modelName);
  }
  scrollToBottom(true);
  closeMobileSidebar();
  await focusChatInput();
}

function getSelectedProviderSelection() {
  return inputRef.value?.getCurrentSelection();
}

async function sendCurrentMessage() {
  if (!canSend.value) return;

  const outgoingDraftKey = activeDraftKey;
  const draftText = draft.value;
  const text = draftText.trim();
  const outgoingParts = buildOutgoingParts(text);
  const selection = getSelectedProviderSelection();

  sending.value = true;
  try {
    let sessionId = currSessionId.value;
    const targetProjectId = selectedProjectId.value;
    const targetProject = selectedProject.value;
    if (!sessionId) {
      sessionId = await newSession();
      await nextTick();
      draft.value = draftText;
      if (targetProjectId) {
        await addSessionToProject(sessionId, targetProjectId);
        sessionProjects[sessionId] = targetProject
          ? {
              project_id: targetProject.project_id,
              title: targetProject.title,
              emoji: targetProject.emoji,
            }
          : null;
        await loadProjectSessions(targetProjectId);
        selectedProjectId.value = null;
      }
    }

    const messageId = crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    writeSessionProviderSelection(sessionId, selection);
    const { userRecord, botRecord } = createLocalExchange({
      sessionId,
      messageId,
      parts: outgoingParts,
    });
    updateTitleFromText(sessionId, text);

    writeChatDraft(outgoingDraftKey, "");
    draft.value = "";
    flushDraft();
    replyTarget.value = null;
    clearStaged({ revokeUrls: false });
    scrollToBottom(true);

    sendMessageStream({
      sessionId,
      messageId,
      parts: outgoingParts,
      transport: transportMode.value,
      enableStreaming: enableStreaming.value,
      selectedProvider: selection?.providerId || "",
      selectedModel: selection?.modelName || "",
      userRecord,
      botRecord,
    });
  } catch (error) {
    console.error("Failed to send message:", error);
  } finally {
    sending.value = false;
    await focusChatInput();
  }
}

function buildOutgoingParts(text: string): MessagePart[] {
  const parts: MessagePart[] = [];
  if (replyTarget.value?.id != null) {
    parts.push({
      type: "reply",
      message_id: replyTarget.value.id,
      selected_text: "",
    });
  }
  if (text) {
    parts.push({ type: "plain", text });
  }
  stagedFiles.value.forEach((file) => {
    parts.push({
      type: file.type,
      attachment_id: file.attachment_id,
      filename: file.filename,
      embedded_url: file.url,
    });
  });
  return parts;
}

function updateTitleFromText(sessionId: string, text: string) {
  const session = sessions.value.find((item) => item.session_id === sessionId);
  const sessionDetail = sessionDetails[sessionId];
  if (session?.display_name || sessionDetail?.display_name || !text) return;
  const title = text.slice(0, 40);
  updateSessionTitle(sessionId, title);
  if (sessionDetail) sessionDetail.display_name = title;
}

function replyPreview(messageId?: string | number, fallback?: string) {
  if (fallback) return truncate(fallback, 80);
  const found = activeMessages.value.find(
    (message) => String(message.id) === String(messageId),
  );
  const text = found ? plainTextFromMessage(found) : "";
  return text ? truncate(text, 80) : tm("reply.replyTo");
}

function plainTextFromMessage(message: ChatRecord) {
  return messageParts(message)
    .filter((part) => part.type === "plain" && part.text)
    .map((part) => part.text)
    .join("\n");
}

function truncate(value: string, max: number) {
  return value.length > max ? `${value.slice(0, max)}...` : value;
}

function scrollToMessage(messageId?: string | number) {
  if (!messageId) return;
  const index = activeMessages.value.findIndex(
    (message) => String(message.id) === String(messageId),
  );
  if (index < 0) return;
  const rows = messagesContainer.value?.querySelectorAll(".message-row");
  rows?.[index]?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function openMessageEdit(message: ChatRecord) {
  messageEditDraft.value = plainTextFromMessage(message);
  editingMessage.value = message;
  nextTick(() => scrollToMessage(message.id));
}

function cancelMessageEdit() {
  editingMessage.value = null;
  messageEditDraft.value = "";
}

async function saveMessageEdit() {
  if (!currSessionId.value || !editingMessage.value) return;
  savingMessageEdit.value = true;
  try {
    const target = editingMessage.value;
    const result = await editMessage(
      currSessionId.value,
      target,
      messageEditDraft.value,
    );
    cancelMessageEdit();

    if (result.needsRegenerate && result.truncatedAfterMessage) {
      const selection = getSelectedProviderSelection();
      writeSessionProviderSelection(currSessionId.value, selection);
      continueEditedMessage({
        sessionId: currSessionId.value,
        sourceRecord: target,
        enableStreaming: enableStreaming.value,
        selectedProvider: selection?.providerId || "",
        selectedModel: selection?.modelName || "",
      });
      scrollToBottom(true);
    } else if (result.needsRegenerate) {
      const index = activeMessages.value.findIndex(
        (message) => String(message.id) === String(target.id),
      );
      const nextBot = activeMessages.value
        .slice(index + 1)
        .find((message) => !isUserMessage(message));
      if (nextBot) {
        await handleRegenerateMessage(nextBot);
      }
    }
  } catch (error) {
    console.error("Failed to edit message:", error);
  } finally {
    savingMessageEdit.value = false;
  }
}

async function handleRegenerateMessage(
  message: ChatRecord,
  selection?: RegenerateModelSelection,
) {
  if (!currSessionId.value || isUserMessage(message)) return;
  message.threads = [];
  const effectiveSelection = selection ?? getSelectedProviderSelection();
  writeSessionProviderSelection(currSessionId.value, effectiveSelection);
  await regenerateMessage(
    currSessionId.value,
    message,
    effectiveSelection?.providerId || "",
    effectiveSelection?.modelName || "",
  );
}

function handleBotTextSelection(event: MouseEvent, message: ChatRecord) {
  if (message.id == null || String(message.id).startsWith("local-")) return;
  const container = event.currentTarget as HTMLElement | null;
  window.setTimeout(() => {
    const selection = window.getSelection();
    const selectedText = selection?.toString().trim() || "";
    if (!selection || !selectedText) {
      threadSelection.visible = false;
      return;
    }
    if (
      !container ||
      !container.contains(selection.anchorNode) ||
      !container.contains(selection.focusNode)
    ) {
      threadSelection.visible = false;
      return;
    }
    const range = selection.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    threadSelection.message = message;
    threadSelection.selectedText = selectedText;
    threadSelection.left = Math.min(
      window.innerWidth - 180,
      Math.max(12, rect.left + rect.width / 2 - 70),
    );
    threadSelection.top = Math.max(12, rect.top - 42);
    threadSelection.visible = true;
  }, 0);
}

async function createThreadFromSelection() {
  const message = threadSelection.message;
  if (!currSessionId.value || !message?.id || !threadSelection.selectedText) return;
  try {
    const response = await axios.post("/api/chat/thread/create", {
      session_id: currSessionId.value,
      parent_message_id: message.id,
      selected_text: threadSelection.selectedText,
    });
    if (response.data?.status !== "ok") {
      toast.error(response.data?.message || tm("thread.createFailed"));
      return;
    }
    const thread = response.data?.data as ChatThread | undefined;
    if (!thread) {
      toast.error(tm("thread.createFailed"));
      return;
    }
    message.threads = message.threads || [];
    if (!message.threads.some((item) => item.thread_id === thread.thread_id)) {
      message.threads.push(thread);
    }
    openThreadPanel(thread);
    window.getSelection()?.removeAllRanges();
  } catch (error) {
    toast.error(
      axios.isAxiosError(error)
        ? error.response?.data?.message || error.message
        : tm("thread.createFailed"),
    );
    console.error("Failed to create thread:", error);
  } finally {
    threadSelection.visible = false;
  }
}

function openThreadPanel(thread: ChatThread) {
  reasoningPanelOpen.value = false;
  activeReasoningTarget.value = null;
  refsSidebarOpen.value = false;
  activeThread.value = thread;
  threadPanelOpen.value = true;
}

function openRefsSidebar(refs: unknown) {
  threadPanelOpen.value = false;
  activeThread.value = null;
  reasoningPanelOpen.value = false;
  activeReasoningTarget.value = null;
  selectedRefs.value =
    refs && typeof refs === "object" ? (refs as Record<string, unknown>) : null;
  refsSidebarOpen.value = true;
}

function openReasoningPanel(payload: {
  message: ChatRecord;
  blockIndex: number;
}) {
  threadPanelOpen.value = false;
  activeThread.value = null;
  refsSidebarOpen.value = false;
  selectedRefs.value = null;
  activeReasoningTarget.value = payload;
  reasoningPanelOpen.value = true;
}

async function deleteThread(thread: ChatThread) {
  if (deletingThread.value) return;
  if (!(await askForConfirmation(tm("thread.confirmDelete"), confirmDialog))) return;
  deletingThread.value = true;
  try {
    await axios.post("/api/chat/thread/delete", {
      thread_id: thread.thread_id,
    });
    removeThreadFromMessages(thread.thread_id);
    if (activeThread.value?.thread_id === thread.thread_id) {
      threadPanelOpen.value = false;
      activeThread.value = null;
    }
  } catch (error) {
    console.error("Failed to delete thread:", error);
  } finally {
    deletingThread.value = false;
  }
}

function removeThreadFromMessages(threadId: string) {
  for (const message of activeMessages.value) {
    if (!message.threads?.length) continue;
    message.threads = message.threads.filter(
      (thread) => thread.thread_id !== threadId,
    );
  }
}

async function handleFilesSelected(files: FileList) {
  const selectedFiles = Array.from(files || []);
  for (const file of selectedFiles) {
    if (file.type.startsWith("image/")) {
      await processAndUploadImage(file);
    } else {
      await processAndUploadFile(file);
    }
  }
}

function toggleStreaming() {
  enableStreaming.value = !enableStreaming.value;
}

async function startRecording() {
  try {
    await startRecorder();
  } catch (error) {
    console.error("Failed to start recording:", error);
    toast.error(tm("voice.error"));
  }
}

async function stopRecording() {
  try {
    const audioFile = await stopRecorder();
    const uploaded = await processAndUploadFile(audioFile);
    if (!uploaded) {
      toast.error(tm("voice.error"));
    }
  } catch (error) {
    console.error("Failed to stop recording:", error);
    toast.error(tm("voice.error"));
  }
}

function handleMessagesScroll() {
  threadSelection.visible = false;
  const container = messagesContainer.value;
  if (!container) return;
  const distance =
    container.scrollHeight - container.scrollTop - container.clientHeight;
  shouldStickToBottom.value = distance < 80;
  maybeLoadEarlierOnScroll(container);
}

async function loadEarlierWithAnchor() {
  const sessionId = currSessionId.value;
  if (!sessionId || activeSessionPagination.value?.loading) return;
  const container = messagesContainer.value;
  const firstId = activeMessages.value[0]?.id;
  const firstRow = firstId == null ? null : findMessageRow(container, firstId);
  const beforeTop = firstRow?.getBoundingClientRect().top;
  const token = ++historyLoadToken;
  suppressAutoScroll.value = true;
  try {
    await loadEarlierMessages(sessionId);
    if (currSessionId.value !== sessionId) return;
    await nextTick();
    if (beforeTop == null || !container || firstId == null) return;
    const row = findMessageRow(container, firstId);
    if (row) {
      container.scrollTop += row.getBoundingClientRect().top - beforeTop;
    }
  } finally {
    if (historyLoadToken === token) suppressAutoScroll.value = false;
  }
}

function findMessageRow(container: HTMLElement | null, messageId: string | number) {
  if (!container) return null;
  return (
    Array.from(
      container.querySelectorAll<HTMLElement>("[data-message-id]"),
    ).find((row) => row.dataset.messageId === String(messageId)) || null
  );
}

function maybeLoadEarlierOnScroll(container: HTMLElement) {
  const sessionId = currSessionId.value;
  const pagination = activeSessionPagination.value;
  if (!sessionId || !pagination) return;
  if (!pagination.has_more || pagination.loading || pagination.error) return;
  if (container.scrollHeight <= container.clientHeight) return;
  if (container.scrollTop > LOAD_EARLIER_SCROLL_THRESHOLD) return;
  void loadEarlierWithAnchor();
}

async function retryCurrentSessionLoad() {
  const sessionId = currSessionId.value;
  if (!sessionId || activeSessionPagination.value?.loading) return;
  if (activeMessages.value.length && activeSessionPagination.value?.has_more) {
    await loadEarlierWithAnchor();
    return;
  }
  await loadSessionMessages(sessionId, true);
}

function scrollToBottom(resumeFollowing = false) {
  if (resumeFollowing) shouldStickToBottom.value = true;
  if (!shouldStickToBottom.value || autoScrollFrame !== null) return;

  autoScrollFrame = window.requestAnimationFrame(() => {
    autoScrollFrame = null;
    const container = messagesContainer.value;
    if (
      !container ||
      suppressAutoScroll.value ||
      !shouldStickToBottom.value
    )
      return;
    container.scrollTop = container.scrollHeight;
    shouldStickToBottom.value = true;
  });
}

async function focusChatInput() {
  await nextTick();
  window.requestAnimationFrame(() => {
    inputRef.value?.focusInput();
  });
}

async function stopCurrentSession() {
  if (!currSessionId.value) return;
  try {
    await stopSession(currSessionId.value);
  } catch (error) {
    console.error("Failed to stop session:", error);
  }
}

function toggleTheme() {
  customizer.SET_UI_THEME(isDark.value ? "PurpleTheme" : "PurpleThemeDark");
}
</script>

<style scoped>
.chat-ui {
  --chat-sidebar-bg: #fbfbfb;
  --chat-session-active-bg: #efefef;
  --chat-page-bg: rgb(var(--v-theme-background));
  --chat-border: rgba(var(--v-border-color), 0.16);
  --chat-muted: rgba(var(--v-theme-on-surface), 0.62);
  display: flex;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: var(--chat-page-bg);
  color: rgb(var(--v-theme-on-surface));
  font-family:
    system-ui,
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    Roboto,
    Oxygen,
    Ubuntu,
    Cantarell,
    "Open Sans",
    "Helvetica Neue",
    sans-serif;
}

.chat-ui.is-dark {
  --chat-sidebar-bg: #2d2d2d;
  --chat-session-active-bg: rgba(255, 255, 255, 0.08);
  --chat-border: rgba(255, 255, 255, 0.1);
}

.chat-sidebar {
  height: 100%;
  background: var(--chat-sidebar-bg);
}

.chat-sidebar.collapsed {
  background: transparent;
}

.chat-sidebar :deep(.v-navigation-drawer__content) {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.sidebar-top {
  padding: 12px;
}

.brand-row {
  display: flex;
  align-items: center;
}

.brand-row {
  justify-content: flex-start;
  min-height: 36px;
  margin-bottom: 8px;
}

.sidebar-toggle,
.new-chat-btn,
.settings-btn {
  color: var(--chat-muted);
  border-radius: 8px;
}

.sidebar-action-icon {
  color: currentcolor;
}

.sidebar-toggle {
  width: 40px;
  height: 40px;
  min-width: 40px;
}

.new-chat-btn,
.settings-btn {
  width: 100%;
  justify-content: flex-start;
  border-radius: 8px;
  text-transform: none;
  font-weight: 500;
}

.sidebar-provider-btn {
  margin-bottom: 8px;
}

.new-chat-btn:not(.icon-only),
.settings-btn:not(.icon-only) {
  padding-inline: 12px;
}

.new-chat-btn.icon-only,
.settings-btn.icon-only {
  width: 40px;
  height: 40px;
  min-width: 40px;
  justify-content: center;
}

.chat-sidebar.collapsed .brand-row,
.chat-sidebar.collapsed .sidebar-footer {
  display: flex;
  justify-content: center;
}

.sidebar-toggle:hover,
.new-chat-btn:hover,
.settings-btn:hover {
  background: var(--chat-session-active-bg);
}

.sidebar-workspace-btn--active {
  background: var(--chat-session-active-bg);
  color: rgb(var(--v-theme-on-surface));
}

.chevron-collapsed {
  transform: rotate(180deg);
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.session-item {
  width: 100%;
  min-height: 38px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  text-align: left;
}

.session-item:hover,
.session-item.active {
  background: var(--chat-session-active-bg);
}

.session-title {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  font-weight: 500;
}

.session-progress {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  flex-shrink: 0;
  transition: right 0.16s ease;
}

.session-actions {
  display: none;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.session-item:hover .session-actions,
.session-item:focus-within .session-actions {
  display: flex;
}

.session-item:hover .session-progress,
.session-item:focus-within .session-progress {
  right: 62px;
}

.session-action-btn {
  color: var(--chat-muted);
}

.session-action-btn:hover {
  color: rgb(var(--v-theme-on-surface));
}

.empty-sessions {
  padding: 12px;
  color: var(--chat-muted);
  font-size: 13px;
}

.session-list-retry {
  align-self: center;
}

.sidebar-footer {
  margin-top: auto;
  padding: 10px 12px 14px;
}

.settings-menu-content {
  min-width: 230px;
  padding: 6px;
}

.settings-menu-value {
  color: var(--chat-muted);
  font-size: 12px;
  margin-right: 4px;
  max-width: 92px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.language-flag {
  display: inline-block;
  width: 20px;
  margin-right: 8px;
}

.chat-main {
  flex: 1;
  min-width: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  position: relative;
}

.chat-main.empty-chat {
  justify-content: center;
}

.provider-workspace-shell {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.provider-workspace-page {
  height: 100%;
  min-height: 0;
}

.messages-panel {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 24px max(24px, calc((100% - 980px) / 2)) 18px;
}

.history-loading {
  z-index: 2;
  pointer-events: none;
}

.history-load-error {
  max-width: 760px;
  margin: 0 auto 12px;
}

.empty-chat .messages-panel {
  flex: 0 0 auto;
  min-height: auto;
  overflow: visible;
  padding: 0 max(24px, calc((100% - 980px) / 2)) 20px;
}

.center-state,
.welcome-state {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}

.empty-chat .welcome-state {
  height: auto;
}

.welcome-title {
  font-size: 28px;
  font-weight: 800;
}

.welcome-subtitle {
  margin-top: 8px;
  color: var(--chat-muted);
  font-size: 16px;
}

.session-project-breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  max-width: min(760px, 82%);
  margin-bottom: 18px;
  color: var(--chat-muted);
  font-size: 13px;
  font-weight: 500;
}

.session-project-breadcrumb span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.thread-selection-action {
  position: fixed;
  z-index: 1200;
  pointer-events: auto;
}

.thread-selection-button {
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.14);
  border-radius: 999px;
  background: rgb(var(--v-theme-surface));
  color: rgb(var(--v-theme-on-surface));
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.14);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.composer-shell {
  position: relative;
  z-index: 1;
  background: var(--chat-page-bg);
  padding: 0 0 18px;
}

.composer-shell::before {
  content: "";
  position: absolute;
  z-index: -1;
  left: 0;
  right: 0;
  top: -36px;
  height: 36px;
  pointer-events: none;
  background: linear-gradient(
    to bottom,
    rgba(var(--v-theme-background), 0),
    var(--chat-page-bg)
  );
}

.composer-shell :deep(.input-area) {
  border-top: 0;
}

.empty-chat .composer-shell {
  padding-bottom: 0;
}

.empty-chat .composer-shell::before {
  display: none;
}

kbd {
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(var(--v-theme-on-surface), 0.08);
  font: inherit;
}

:deep(.hr-node) {
    margin-top: 1.25rem;
    margin-bottom: 1.25rem;
    opacity: 0.5;
    border-top-width: .3px;
}

:deep(.paragraph-node) {
    margin: .5rem 0;
    line-height: 1.7;
}

:deep(.list-node) {
    margin-top: .5rem;
    margin-bottom: .5rem;
}

@media (max-width: 760px) {
  .messages-panel {
    padding: 18px 14px;
  }

  .composer-shell,
  .project-composer-shell {
    padding: 0;
  }
}
</style>
