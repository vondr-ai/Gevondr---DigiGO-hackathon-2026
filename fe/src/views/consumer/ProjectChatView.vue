<script setup lang="ts">
import MarkdownIt from 'markdown-it'
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { streamProjectChat } from '@/api/project-chat'
import { listConsumerProjects } from '@/api/projects'
import type {
  ProjectChatMessage,
  ProjectChatRetrievalEvent,
  ProjectChatToolEvent,
} from '@/types'
import { getErrorMessage } from '@/utils/errors'

interface ChatMessageVm extends ProjectChatMessage {
  id: string
  kind: 'message'
  streaming?: boolean
  error?: boolean
}

interface ChatRetrievalVm {
  id: string
  kind: 'retrieval'
  phase: 'idle' | 'started' | 'progress' | 'completed'
  sourcesUsed: number
  queryCount: number
  completedQueries: number
  toolBaseSourcesUsed: number
}

type ChatRowVm = ChatMessageVm | ChatRetrievalVm

const markdown = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
})

const defaultLinkOpen =
  markdown.renderer.rules.link_open ??
  ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))

markdown.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, idx, options, env, self)
}

const route = useRoute()
const router = useRouter()
const projectId = route.params.id as string

const initialDraft = ''
const projectName = ref('Project')
const draft = ref(initialDraft)
const messages = ref<ChatRowVm[]>([])
const error = ref('')
const isStreaming = ref(false)
const conversationRef = ref<HTMLDivElement | null>(null)
const composerRef = ref<HTMLTextAreaElement | null>(null)

let activeController: AbortController | null = null

function renderMarkdown(content: string): string {
  return markdown.render(content)
}

function isChatMessageVm(message: ChatRowVm): message is ChatMessageVm {
  return message.kind === 'message'
}

function buildRequestMessages(nextUserMessage: ProjectChatMessage): ProjectChatMessage[] {
  return [...messages.value.filter(isChatMessageVm), nextUserMessage].map(({ role, content }) => ({
    role,
    content,
  }))
}

function scrollToConversationEnd(): void {
  requestAnimationFrame(() => {
    const node = conversationRef.value
    if (!node) return
    node.scrollTop = node.scrollHeight
  })
}

function focusComposer(): void {
  nextTick(() => composerRef.value?.focus())
}

function removeChatRow(id: string): void {
  messages.value = messages.value.filter((message) => message.id !== id)
}

function formatRetrievalSummary(message: ChatRetrievalVm): string {
  if (message.phase === 'completed') {
    return 'Sources consulted'
  }
  if (message.queryCount > 0) {
    return 'Searching documents'
  }
  return 'Preparing search'
}

function formatRetrievalDetail(message: ChatRetrievalVm): string {
  const sourceLabel = `${message.sourcesUsed} ${message.sourcesUsed === 1 ? 'source' : 'sources'}`

  if (message.phase === 'completed') {
    if (message.queryCount > 0) {
      return `${sourceLabel} across ${message.queryCount} ${
        message.queryCount === 1 ? 'search' : 'searches'
      }`
    }
    return sourceLabel
  }

  if (message.queryCount > 0) {
    return `${message.completedQueries}/${message.queryCount} searches complete - ${sourceLabel}`
  }

  return `${sourceLabel} so far`
}

function handleToolEvent(message: ChatRetrievalVm, payload: ProjectChatToolEvent): void {
  if (payload.tool !== 'search_project') return

  if (payload.phase === 'started') {
    message.toolBaseSourcesUsed = message.sourcesUsed
    message.phase = 'started'
    return
  }

  message.phase = 'completed'
  message.sourcesUsed = Math.max(
    message.sourcesUsed,
    payload.uniqueDocumentCount ?? message.sourcesUsed,
  )
}

function handleRetrievalEvent(message: ChatRetrievalVm, payload: ProjectChatRetrievalEvent): void {
  message.phase = payload.phase
  message.queryCount = payload.queryCount
  message.completedQueries = payload.completedQueries ?? message.completedQueries
  message.sourcesUsed = Math.max(message.sourcesUsed, message.toolBaseSourcesUsed + payload.sourcesUsed)
}

function finalizeRetrievalMessage(message: ChatRetrievalVm): void {
  if (message.phase === 'idle') return
  message.phase = 'completed'
}

function isVisibleRetrievalMessage(message: ChatRetrievalVm): boolean {
  return message.phase !== 'idle'
}

function isVisibleAssistantMessage(message: ChatMessageVm): boolean {
  return message.role !== 'assistant' || Boolean(message.content) || !message.streaming
}

function resetChat(options: { abortActive?: boolean } = {}): void {
  if (options.abortActive && activeController) {
    activeController.abort()
  }
  messages.value = []
  error.value = ''
  isStreaming.value = false
  activeController = null
  draft.value = initialDraft
  scrollToConversationEnd()
  focusComposer()
}

async function fetchProjectContext(): Promise<void> {
  try {
    const res = await listConsumerProjects()
    const currentProject = res.items.find((item) => item.id === projectId)
    if (!currentProject) {
      error.value = 'Project is niet gevonden of niet toegankelijk.'
      return
    }
    projectName.value = currentProject.name
  } catch (err) {
    error.value = getErrorMessage(err, 'Projectgegevens konden niet worden geladen.')
  }
}

async function sendMessage(): Promise<void> {
  const content = draft.value.trim()
  if (!content || isStreaming.value) return

  error.value = ''

  const userMessage = reactive<ChatMessageVm>({
    id: crypto.randomUUID(),
    kind: 'message',
    role: 'user',
    content,
  })
  const retrievalMessage = reactive<ChatRetrievalVm>({
    id: crypto.randomUUID(),
    kind: 'retrieval',
    phase: 'idle',
    sourcesUsed: 0,
    queryCount: 0,
    completedQueries: 0,
    toolBaseSourcesUsed: 0,
  })
  const assistantMessage = reactive<ChatMessageVm>({
    id: crypto.randomUUID(),
    kind: 'message',
    role: 'assistant',
    content: '',
    streaming: true,
  })

  const requestMessages = buildRequestMessages(userMessage)
  messages.value.push(userMessage, retrievalMessage, assistantMessage)
  draft.value = ''
  isStreaming.value = true
  const controller = new AbortController()
  activeController = controller
  scrollToConversationEnd()

  try {
    await streamProjectChat(
      projectId,
      { messages: requestMessages },
      {
        signal: controller.signal,
        onRetrieval: async (payload) => {
          handleRetrievalEvent(retrievalMessage, payload)
          await nextTick()
          scrollToConversationEnd()
        },
        onToken: async (payload) => {
          assistantMessage.content += payload.text
          await nextTick()
          scrollToConversationEnd()
        },
        onTool: async (payload) => {
          handleToolEvent(retrievalMessage, payload)
          await nextTick()
          scrollToConversationEnd()
        },
        onDone: async (payload) => {
          assistantMessage.content = payload.output || assistantMessage.content
          assistantMessage.streaming = false
          if (retrievalMessage.phase === 'idle') {
            removeChatRow(retrievalMessage.id)
          } else {
            finalizeRetrievalMessage(retrievalMessage)
          }
          await nextTick()
          scrollToConversationEnd()
        },
        onError: (payload) => {
          assistantMessage.streaming = false
          assistantMessage.error = true
          if (!assistantMessage.content) {
            assistantMessage.content = 'Er ging iets mis tijdens het genereren van het antwoord.'
          }
          error.value = payload.message
          if (retrievalMessage.phase === 'idle') {
            removeChatRow(retrievalMessage.id)
          } else {
            finalizeRetrievalMessage(retrievalMessage)
          }
        },
      },
    )
  } catch (err) {
    if (controller.signal.aborted) {
      assistantMessage.streaming = false
      if (!assistantMessage.content.trim()) {
        removeChatRow(assistantMessage.id)
      }
      if (retrievalMessage.phase === 'idle') {
        removeChatRow(retrievalMessage.id)
      } else {
        finalizeRetrievalMessage(retrievalMessage)
      }
      return
    }

    assistantMessage.streaming = false
    assistantMessage.error = true
    if (!assistantMessage.content) {
      assistantMessage.content = 'Ik kon geen antwoord genereren.'
    }
    error.value = err instanceof Error ? err.message : 'Chatbericht kon niet worden verstuurd.'
    if (retrievalMessage.phase === 'idle') {
      removeChatRow(retrievalMessage.id)
    } else {
      finalizeRetrievalMessage(retrievalMessage)
    }
  } finally {
    isStreaming.value = false
    if (activeController === controller) {
      activeController = null
    }
    scrollToConversationEnd()
    focusComposer()
  }
}

function stopStreaming(): void {
  activeController?.abort()
}

async function openProtectedDocument(url: URL): Promise<void> {
  const token = localStorage.getItem('token')
  const response = await fetch(url.toString(), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })

  if (response.status === 401) {
    localStorage.removeItem('token')
    window.location.href = '/login'
    return
  }

  if (!response.ok) {
    throw new Error('Document kon niet worden geopend.')
  }

  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)

  // Extract filename from Content-Disposition header
  const disposition = response.headers.get('content-disposition') ?? ''
  const filenameMatch = disposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)"?/i)
  const filename = filenameMatch ? decodeURIComponent(filenameMatch[1]) : 'document'
  const ext = filename.split('.').pop()?.toLowerCase() ?? ''

  if (ext === 'pdf') {
    window.open(objectUrl, '_blank', 'noopener,noreferrer')
  } else {
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000)
}

async function handleMessageClick(event: MouseEvent): Promise<void> {
  const target = event.target
  if (!(target instanceof HTMLElement)) return

  const anchor = target.closest('a')
  if (!(anchor instanceof HTMLAnchorElement)) return

  const url = new URL(anchor.href, window.location.origin)
  const isProtectedDocumentLink =
    url.origin === window.location.origin &&
    /^\/api\/v1\/projects\/[^/]+\/documents\/[^/]+\/open$/.test(url.pathname)

  if (!isProtectedDocumentLink) return

  event.preventDefault()
  error.value = ''

  try {
    await openProtectedDocument(url)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Document kon niet worden geopend.'
  }
}

onMounted(async () => {
  await fetchProjectContext()
  focusComposer()
})

onBeforeUnmount(() => {
  activeController?.abort()
})
</script>

<template>
  <div class="min-h-screen bg-background chat-canvas">
    <main class="flex min-h-screen w-full flex-col px-6 py-8 lg:px-12 lg:py-10">
      <button
        type="button"
        class="inline-flex w-fit items-center gap-2 text-sm text-text-secondary transition hover:text-text"
        @click="router.push({ name: 'consumer-projects' })"
      >
        <span aria-hidden="true">&larr;</span>
        <span>Terug naar projecten</span>
      </button>

      <section class="mt-8 flex min-h-0 flex-1 flex-col">
        <div class="flex w-full items-start justify-between gap-4">
          <div>
            <p class="text-[11px] font-semibold uppercase tracking-[0.26em] text-consumer/80">Live chat</p>
            <h1 class="mt-4 text-3xl font-semibold tracking-tight text-text sm:text-4xl">
              Vraag iets over {{ projectName }}
            </h1>
          </div>
          <button
            type="button"
            class="inline-flex h-11 w-11 items-center justify-center rounded-full border border-slate-200 bg-white/80 text-text shadow-sm transition hover:border-slate-300 hover:bg-white"
            aria-label="Nieuwe chat"
            title="Nieuwe chat"
            @click="resetChat({ abortActive: true })"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" class="h-5 w-5">
              <path
                d="M12 5v14M5 12h14"
                fill="none"
                stroke="currentColor"
                stroke-linecap="round"
                stroke-width="2"
              />
            </svg>
          </button>
        </div>

        <p
          v-if="error"
          class="mt-8 w-full max-w-3xl rounded-2xl bg-red-50/90 px-4 py-3 text-sm text-red-700"
        >
          {{ error }}
        </p>

        <div
          ref="conversationRef"
          class="mt-10 flex-1 overflow-y-auto pr-1 pb-10"
        >
          <div class="flex w-full flex-col gap-6">
            <template v-for="message in messages" :key="message.id">
              <article
                v-if="
                  (message.kind !== 'retrieval' || isVisibleRetrievalMessage(message)) &&
                  (message.kind !== 'message' || isVisibleAssistantMessage(message))
                "
                class="flex"
                :class="
                  message.kind === 'message' && message.role === 'user'
                    ? 'justify-end'
                    : 'justify-start'
                "
              >
                <div
                  :class="
                    message.kind === 'message' && message.role === 'user'
                      ? 'max-w-xl'
                      : 'w-full max-w-3xl'
                  "
                >
                  <div
                    v-if="message.kind === 'retrieval' && isVisibleRetrievalMessage(message)"
                    class="retrieval-card"
                  >
                    <div class="retrieval-card__header">
                      <span
                        v-if="message.phase !== 'completed'"
                        class="chat-spinner chat-spinner--small"
                        aria-hidden="true"
                      />
                      <span
                        v-else
                        class="retrieval-card__check"
                        aria-hidden="true"
                      >
                        OK
                      </span>
                      <span class="retrieval-card__title">{{ formatRetrievalSummary(message) }}</span>
                    </div>
                    <p class="retrieval-card__detail">
                      {{ formatRetrievalDetail(message) }}
                    </p>
                  </div>
                  <div
                    v-else-if="message.kind === 'message' && message.role === 'assistant'"
                    class="chat-markdown text-[15px] leading-8 text-text sm:text-base"
                    :class="message.error ? 'rounded-3xl bg-red-50 px-5 py-4 text-red-900' : ''"
                    @click="handleMessageClick"
                    v-html="renderMarkdown(message.content)"
                  />
                  <p
                    v-else-if="message.kind === 'message'"
                    class="inline-block whitespace-pre-wrap rounded-[1.75rem] bg-[#e9edf1] px-5 py-4 text-sm leading-7 text-text sm:text-[15px]"
                  >
                    {{ message.content }}
                  </p>
                </div>
              </article>
            </template>
          </div>
        </div>

        <div class="sticky bottom-0 mt-4 pt-8 composer-fade">
          <form class="flex w-full flex-col gap-4" @submit.prevent="sendMessage">
            <div class="rounded-[2rem] bg-white/88 px-1 py-1 shadow-[0_28px_70px_rgba(15,23,42,0.16)] backdrop-blur-sm">
              <label class="sr-only" for="project-chat-input">Chatbericht</label>
              <textarea
                id="project-chat-input"
                ref="composerRef"
                v-model="draft"
                rows="2"
                placeholder="Begin met typen...."
                class="w-full resize-none border-0 bg-transparent px-5 py-3 text-[15px] leading-6 text-text outline-none placeholder:text-text-muted"
                @keydown.enter.exact.prevent="sendMessage"
              />
              <div class="flex flex-col gap-3 px-4 pb-2 pt-1 text-sm sm:flex-row sm:items-center sm:justify-between">
                <div class="flex items-center gap-2 self-end sm:self-auto">
                  <button
                    v-if="isStreaming"
                    type="button"
                    class="rounded-full px-4 py-1.5 text-sm text-text-secondary transition hover:bg-white hover:text-text"
                    @click="stopStreaming"
                  >
                    Stop
                  </button>
                  <button
                    type="submit"
                    class="inline-flex h-11 w-11 items-center justify-center rounded-full bg-text text-white transition hover:bg-primary disabled:cursor-not-allowed disabled:opacity-50"
                    :disabled="!draft.trim() || isStreaming"
                    aria-label="Verstuur bericht"
                  >
                    <svg aria-hidden="true" viewBox="0 0 24 24" class="h-5 w-5">
                      <path
                        d="M7 17 17 7m0 0H9.5M17 7v7.5"
                        fill="none"
                        stroke="currentColor"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                      />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          </form>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.chat-canvas {
  background:
    radial-gradient(circle at top left, rgba(16, 185, 129, 0.08), transparent 28%),
    linear-gradient(180deg, #fbfcfd 0%, #f7f9fb 100%);
}

.composer-fade {
  background: linear-gradient(180deg, rgba(247, 249, 251, 0) 0%, rgba(247, 249, 251, 0.82) 24%, rgba(247, 249, 251, 0.98) 100%);
}

.retrieval-card {
  width: fit-content;
  max-width: min(32rem, 100%);
  padding: 0.25rem 0;
}

.retrieval-card__header {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.retrieval-card__title {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(71, 85, 105, 0.96);
}

.retrieval-card__detail {
  margin: 0.45rem 0 0;
  padding-left: 1.45rem;
  font-size: 0.93rem;
  line-height: 1.45;
  color: var(--color-text-secondary);
}

.retrieval-card__check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 0.95rem;
  height: 0.95rem;
  border-radius: 9999px;
  background: rgba(16, 185, 129, 0.14);
  color: rgb(5, 150, 105);
  font-size: 0.58rem;
  font-weight: 700;
}

.chat-markdown :deep(*) {
  min-width: 0;
}

.chat-markdown :deep(p) {
  margin: 0;
}

.chat-markdown :deep(p + p),
.chat-markdown :deep(ul),
.chat-markdown :deep(ol),
.chat-markdown :deep(pre),
.chat-markdown :deep(blockquote),
.chat-markdown :deep(h1),
.chat-markdown :deep(h2),
.chat-markdown :deep(h3) {
  margin-top: 1rem;
}

.chat-markdown :deep(h1),
.chat-markdown :deep(h2),
.chat-markdown :deep(h3) {
  font-size: 1.05em;
  line-height: 1.45;
}

.chat-markdown :deep(ul),
.chat-markdown :deep(ol) {
  padding-left: 1.25rem;
}

.chat-markdown :deep(li + li) {
  margin-top: 0.35rem;
}

.chat-markdown :deep(a) {
  color: var(--color-text);
  font-weight: 600;
  text-decoration: underline;
  text-decoration-color: rgba(17, 24, 39, 0.28);
  text-underline-offset: 0.24em;
}

.chat-markdown :deep(code) {
  border-radius: 0.45rem;
  background: rgba(17, 24, 39, 0.06);
  color: var(--color-text);
  padding: 0.08rem 0.35rem;
  font-size: 0.92em;
}

.chat-markdown :deep(pre) {
  overflow-x: auto;
  border-radius: 1.25rem;
  background: #101827;
  color: #f8fafc;
  padding: 1rem 1.1rem;
}

.chat-markdown :deep(pre code) {
  background: transparent;
  color: inherit;
  padding: 0;
}

.chat-markdown :deep(blockquote) {
  border-left: 2px solid rgba(16, 185, 129, 0.7);
  padding-left: 0.9rem;
  color: var(--color-text-secondary);
}

.chat-spinner {
  width: 0.95rem;
  height: 0.95rem;
  border-radius: 9999px;
  border: 2px solid rgba(17, 24, 39, 0.14);
  border-top-color: rgba(17, 24, 39, 0.72);
  animation: chat-spin 0.7s linear infinite;
}

.chat-spinner--small {
  width: 0.8rem;
  height: 0.8rem;
}

@keyframes chat-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
