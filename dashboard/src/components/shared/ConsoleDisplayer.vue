<script setup>
import { useCommonStore } from '@/stores/common';
import axios from 'axios';
import { EventSourcePolyfill } from 'event-source-polyfill';
import { useModuleI18n } from '@/i18n/composables';

const { tm } = useModuleI18n('features/console');
</script>

<template>
  <div class="console-displayer-wrapper" id="console-wrapper">
    <div class="filter-controls mb-2" v-if="showLevelBtns || showSearch">
      <v-chip-group v-model="selectedLevels" column multiple>
        <v-chip v-for="level in logLevels" :key="level" :color="getLevelColor(level)" filter variant="flat" size="small"
          :text-color="level === 'DEBUG' || level === 'INFO' ? 'black' : 'white'" class="font-weight-medium">
          {{ level }}
        </v-chip>
      </v-chip-group>
      <v-text-field
        v-if="showSearch"
        v-model="searchInput"
        class="log-search-field"
        density="compact"
        variant="solo-filled"
        flat
        hide-details
        single-line
        clearable
        prepend-inner-icon="mdi-magnify"
        :aria-label="tm('search.label')"
        :placeholder="tm('search.placeholder')"
      />
      <v-spacer></v-spacer>
      <v-btn
        :icon="isFullscreen ? 'mdi-fullscreen-exit' : 'mdi-fullscreen'"
        variant="text"
        density="compact"
        class="me-4 fullscreen-btn"
        @click="toggleFullscreen"
      ></v-btn>
    </div>

    <div id="term" class="console-term">
    </div>
  </div>
</template>

<script>
export default {
  name: 'ConsoleDisplayer',
  data() {
    return {
      autoScroll: true,
      isFullscreen: false,
      logColorAnsiMap: {
        '\u001b[1;34m': 'color: #6cb6d9; font-weight: bold;',
        '\u001b[1;36m': 'color: #72c4cc; font-weight: bold;',
        '\u001b[1;33m': 'color: #d4b95e; font-weight: bold;',
        '\u001b[31m': 'color: #d46a6a;',
        '\u001b[1;31m': 'color: #e06060; font-weight: bold;',
        '\u001b[0m': 'color: inherit; font-weight: normal;',
        '\u001b[32m': 'color: #6cc070;',
        'default': 'color: #c8c8c8;'
      },
      logLevels: ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
      selectedLevels: [0, 1, 2, 3, 4],
      levelColors: {
        'DEBUG': 'grey',
        'INFO': 'blue-lighten-3',
        'WARNING': 'amber',
        'ERROR': 'red',
        'CRITICAL': 'purple'
      },
      localLogCache: [],
      searchInput: '',
      searchKeyword: '',
      searchTimer: null,
      eventSource: null,
      retryTimer: null,
      retryAttempts: 0,           
      maxRetryAttempts: 10,       
      baseRetryDelay: 1000,       
      lastEventId: null,          
    }
  },
  computed: {
    commonStore() {
      return useCommonStore();
    },
  },
  props: {
    historyNum: {
      type: String,
      default: "-1"
    },
    showLevelBtns: {
      type: Boolean,
      default: true
    },
    showSearch: {
      type: Boolean,
      default: false
    }
  },
  watch: {
    selectedLevels: {
      handler() {
        this.refreshDisplay();
      },
      deep: true
    },
    searchInput(value) {
      if (this.searchTimer) clearTimeout(this.searchTimer);
      this.searchTimer = setTimeout(() => {
        this.searchTimer = null;
        const keyword = (value || '').trim();
        if (keyword !== this.searchKeyword) {
          this.searchKeyword = keyword;
          this.refreshDisplay();
        }
      }, 250);
    }
  },
  async mounted() {
    await this.fetchLogHistory();
    this.connectSSE();
    document.addEventListener('fullscreenchange', this.handleFullscreenChange);
  },
  beforeUnmount() {
    document.removeEventListener('fullscreenchange', this.handleFullscreenChange);
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    if (this.searchTimer) {
      clearTimeout(this.searchTimer);
      this.searchTimer = null;
    }
    this.retryAttempts = 0;
  },
  methods: {
    connectSSE() {
      if (this.eventSource) {
        this.eventSource.close();
        this.eventSource = null;
      }

      console.log(`正在连接日志流... (尝试次数: ${this.retryAttempts})`);
      
      const token = localStorage.getItem('token');

      this.eventSource = new EventSourcePolyfill('/api/live-log', {
        headers: {
            'Authorization': token ? `Bearer ${token}` : ''
        },
        heartbeatTimeout: 300000, 
        withCredentials: true 
      });

      this.eventSource.onopen = () => {
        console.log('日志流连接成功！');
        this.retryAttempts = 0;

        if (!this.lastEventId) {
            this.fetchLogHistory();
        }
      };

      this.eventSource.onmessage = (event) => {
        try {
          if (event.lastEventId) {
            this.lastEventId = event.lastEventId;
          }

          const payload = JSON.parse(event.data);
          this.processNewLogs([payload]);
        } catch (e) {
          console.error('解析日志失败:', e);
        }
      };

      this.eventSource.onerror = (err) => {

        if (err.status === 401) {
            console.error('鉴权失败 (401)，可能是 Token 过期了。');

        } else {
            console.warn('日志流连接错误:', err);
        }
        
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }

        if (this.retryAttempts >= this.maxRetryAttempts) {
            console.error('❌ 已达到最大重试次数，停止重连。请刷新页面重试。');
            return; 
        }

        const delay = Math.min(
            this.baseRetryDelay * Math.pow(2, this.retryAttempts),
            30000
        );
        
        console.log(`⏳ ${delay}ms 后尝试第 ${this.retryAttempts + 1} 次重连...`);

        if (this.retryTimer) {
          clearTimeout(this.retryTimer);
          this.retryTimer = null;
        }

        this.retryTimer = setTimeout(async () => {
          this.retryAttempts++;
          
          if (!this.lastEventId) {
             await this.fetchLogHistory();
          }
          
          this.connectSSE();
        }, delay);
      };
    },

    processNewLogs(newLogs) {
      if (!newLogs || newLogs.length === 0) return;

      let hasUpdate = false;

      newLogs.forEach(log => {

        const exists = this.localLogCache.some(existing => 
          existing.time === log.time && 
          existing.data === log.data &&
          existing.level === log.level
        );
        
        if (!exists) {
            this.localLogCache.push(log);
            hasUpdate = true;
            
            if (this.isLevelSelected(log.level) && this.matchesKeyword(log)) {
              this.printLog(log.data);
            }
        }
      });

      if (hasUpdate) {
        this.localLogCache.sort((a, b) => a.time - b.time);
        
        const maxSize = this.commonStore.log_cache_max_len || 200;
        if (this.localLogCache.length > maxSize) {
           this.localLogCache.splice(0, this.localLogCache.length - maxSize);
        }
      }
    },

    async fetchLogHistory() {
      try {
        const res = await axios.get('/api/log-history');
        if (res.data.data.logs && res.data.data.logs.length > 0) {
          this.processNewLogs(res.data.data.logs);
        }
      } catch (err) {
        console.error('Failed to fetch log history:', err);
      }
    },
    
    getLevelColor(level) {
      return this.levelColors[level] || 'grey';
    },

    isLevelSelected(level) {
      for (let i = 0; i < this.selectedLevels.length; ++i) {
        let level_ = this.logLevels[this.selectedLevels[i]]
        if (level_ === level) {
          return true;
        }
      }
      return false;
    },

    matchesKeyword(log) {
      if (!this.searchKeyword) return true;
      const text = (log.data || '').replace(/\u001b\[[0-9;]*m/g, '').toLowerCase();
      return text.includes(this.searchKeyword.toLowerCase());
    },

    appendHighlightedText(element, text) {
      const keyword = this.searchKeyword;
      if (!keyword || !text) {
        element.textContent = text || '';
        return;
      }
      const cleanText = text.replace(/\u001b\[[0-9;]*m/g, '');
      const lowerText = cleanText.toLowerCase();
      const lowerKeyword = keyword.toLowerCase();
      let cursor = 0;
      let index = lowerText.indexOf(lowerKeyword);
      while (index !== -1) {
        if (index > cursor) element.appendChild(document.createTextNode(cleanText.slice(cursor, index)));
        const highlight = document.createElement('span');
        highlight.className = 'console-log-highlight';
        highlight.textContent = cleanText.slice(index, index + keyword.length);
        element.appendChild(highlight);
        cursor = index + keyword.length;
        index = lowerText.indexOf(lowerKeyword, cursor);
      }
      if (cursor < cleanText.length) element.appendChild(document.createTextNode(cleanText.slice(cursor)));
    },

    refreshDisplay() {
      const termElement = document.getElementById('term');
      if (termElement) {
        termElement.innerHTML = '';
        
        if (this.localLogCache && this.localLogCache.length > 0) {
          this.localLogCache.forEach(logItem => {
            if (this.isLevelSelected(logItem.level) && this.matchesKeyword(logItem)) {
              this.printLog(logItem.data);
            }
          });
        }
      }
    },

    toggleAutoScroll() {
      this.autoScroll = !this.autoScroll;
    },

    toggleFullscreen() {
      const container = document.getElementById('console-wrapper');
      if (!document.fullscreenElement) {
        container.requestFullscreen().catch(err => {
          console.error(`Error attempting to enable full-screen mode: ${err.message}`);
        });
      } else {
        document.exitFullscreen();
      }
    },

    handleFullscreenChange() {
      this.isFullscreen = !!document.fullscreenElement;
    },

    appendLogContent(element, log) {
      const levelMatch = log.match(/\[(DEBG|INFO|WARN|ERRO|CRIT|DEBUG|WARNING|ERROR|CRITICAL)\]/);
      if (!levelMatch) {
        this.appendHighlightedText(element, `${log}`);
        return;
      }

      const levelStart = levelMatch.index;
      const levelEnd = levelStart + levelMatch[0].length;
      const prefix = log.slice(0, levelStart).trimEnd();
      const message = log.slice(levelEnd).trimStart();

      const prefixSpan = document.createElement('span');
      prefixSpan.className = 'console-log-prefix';
      this.appendHighlightedText(prefixSpan, prefix);

      const levelSpan = document.createElement('span');
      levelSpan.className = 'console-log-level';
      this.appendHighlightedText(levelSpan, levelMatch[0]);

      const messageSpan = document.createElement('span');
      messageSpan.className = 'console-log-message';
      this.appendHighlightedText(messageSpan, message);

      element.classList.add('console-log-line--structured');
      element.appendChild(prefixSpan);
      element.appendChild(levelSpan);
      element.appendChild(messageSpan);
    },

    printLog(log) {
      let ele = document.getElementById('term')
      if (!ele) {
        return;
      }
      
      let span = document.createElement('pre')
      let style = this.logColorAnsiMap['default']
      for (let key in this.logColorAnsiMap) {
        if (log.startsWith(key)) {
          style = this.logColorAnsiMap[key]
          log = log.replace(key, '').replace('\u001b[0m', '')
          break
        }
      }

      span.style = style
      span.classList.add('console-log-line', 'fade-in')
      this.appendLogContent(span, log);
      ele.appendChild(span)
      if (this.autoScroll) {
        ele.scrollTop = ele.scrollHeight
      }
    }
  },
}
</script>

<style scoped>
.console-displayer-wrapper {
  height: 100%;
  display: flex;
  flex-direction: column;
}

#console-wrapper:fullscreen {
  --v-theme-on-surface: 255, 255, 255;
  background-color: #1e1e1e;
  color: #fff;
  padding: 20px;
}

#console-wrapper:fullscreen :deep(.v-switch__track) {
  --v-theme-surface-variant: 163, 163, 163;
}

.filter-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.console-term {
  background-color: #1e1e1e;
  border-radius: 8px;
  height: 100%;
  overflow-y: auto;
  overflow-x: auto;
  padding: 16px;
}

.log-search-field {
  flex: 0 1 260px;
  max-width: 260px;
  min-width: 160px;
}

.fullscreen-btn {
    color: rgba(255, 255, 255, 0.7) !important; /* 提高在深色背景下的对比度 */
}

:deep(.console-log-line) {
  display: block;
  margin: 0 0 2px;
  font-family: SFMono-Regular, Menlo, Monaco, Consolas, var(--astrbot-font-cjk-mono), monospace;
  font-size: 12px;
  white-space: pre-wrap;
}

:deep(.console-log-line--structured) {
  display: grid;
  grid-template-columns: max-content max-content minmax(0, 1fr);
  column-gap: 8px;
  align-items: start;
  white-space: normal;
}

:deep(.console-log-prefix),
:deep(.console-log-level),
:deep(.console-log-message) {
  min-width: 0;
  white-space: pre-wrap;
}

:deep(.console-log-highlight) {
  background: rgba(255, 213, 79, 0.35);
  border-radius: 2px;
}

:deep(.console-log-level) {
  font-variant-numeric: tabular-nums;
}

:deep(.console-log-message) {
  overflow-wrap: anywhere;
}

@media (max-width: 768px) {
  :deep(.console-log-line--structured) {
    grid-template-columns: 1fr;
  }
  :deep(.console-log-prefix:empty),
  :deep(.console-log-level:empty) {
    display: none;
  }
}

:deep(.fade-in) {
  animation: fadeIn 0.3s;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
}
</style>
