import type {
  ProjectChatMessage,
  ProjectChatRetrievalEvent,
  ProjectChatToolEvent,
  ProjectChatUsage,
} from '@/types'

interface ProjectChatStreamRequest {
  messages: ProjectChatMessage[]
  filters?: {
    norms?: string[]
    document_ids?: string[]
  }
}

interface ProjectChatStatusEvent {
  phase: string
}

interface ProjectChatTokenEvent {
  text: string
}

interface ProjectChatDoneEvent {
  output: string
  usage: ProjectChatUsage
}

interface ProjectChatErrorEvent {
  message: string
}

interface StreamProjectChatOptions {
  signal?: AbortSignal
  onStatus?: (payload: ProjectChatStatusEvent) => void | Promise<void>
  onRetrieval?: (payload: ProjectChatRetrievalEvent) => void | Promise<void>
  onToken?: (payload: ProjectChatTokenEvent) => void | Promise<void>
  onTool?: (payload: ProjectChatToolEvent) => void | Promise<void>
  onDone?: (payload: ProjectChatDoneEvent) => void | Promise<void>
  onError?: (payload: ProjectChatErrorEvent) => void | Promise<void>
}

function buildApiUrl(path: string): string {
  return new URL(path, window.location.origin).toString()
}

async function buildApiError(response: Response): Promise<Error> {
  const fallbackMessage = `Chat request failed with status ${response.status}.`
  const contentType = response.headers.get('content-type') ?? ''

  try {
    if (contentType.includes('application/json')) {
      const payload = await response.json()
      const message =
        payload?.detail?.error?.message ??
        payload?.error?.message ??
        payload?.message ??
        fallbackMessage
      return new Error(message)
    }

    const text = await response.text()
    return new Error(text || fallbackMessage)
  } catch {
    return new Error(fallbackMessage)
  }
}

function waitForBrowserPaint(): Promise<void> {
  return new Promise((resolve) => {
    if (typeof window === 'undefined' || typeof window.requestAnimationFrame !== 'function') {
      resolve()
      return
    }
    window.requestAnimationFrame(() => resolve())
  })
}

async function dispatchSseEvent(rawEvent: string, options: StreamProjectChatOptions): Promise<void> {
  const lines = rawEvent.split('\n')
  let eventName = 'message'
  const dataLines: string[] = []

  for (const line of lines) {
    if (!line || line.startsWith(':')) continue
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim()
      continue
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }

  if (dataLines.length === 0) return

  const payload = JSON.parse(dataLines.join('\n'))
  if (eventName === 'status') {
    await options.onStatus?.(payload)
    return
  }
  if (eventName === 'retrieval') {
    await options.onRetrieval?.(payload)
    await waitForBrowserPaint()
    return
  }
  if (eventName === 'token') {
    await options.onToken?.(payload)
    await waitForBrowserPaint()
    return
  }
  if (eventName === 'tool') {
    await options.onTool?.(payload)
    return
  }
  if (eventName === 'done') {
    await options.onDone?.(payload)
    return
  }
  if (eventName === 'error') {
    await options.onError?.(payload)
  }
}

export async function streamProjectChat(
  projectId: string,
  body: ProjectChatStreamRequest,
  options: StreamProjectChatOptions = {},
): Promise<void> {
  const token = localStorage.getItem('token')
  const response = await fetch(buildApiUrl(`/api/v1/projects/${projectId}/chat/stream`), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal: options.signal,
  })

  if (response.status === 401) {
    localStorage.removeItem('token')
    window.location.href = '/login'
    throw new Error('Session expired.')
  }

  if (!response.ok) {
    throw await buildApiError(response)
  }

  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('Streaming is not available in this browser.')
  }

  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
    buffer = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n')

    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary).trim()
      buffer = buffer.slice(boundary + 2)
      if (rawEvent) {
        await dispatchSseEvent(rawEvent, options)
      }
      boundary = buffer.indexOf('\n\n')
    }

    if (done) break
  }

  const finalEvent = buffer.trim()
  if (finalEvent) {
    await dispatchSseEvent(finalEvent, options)
  }
}
