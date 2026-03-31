import axios from 'axios'

export function getErrorMessage(error: unknown, fallback = 'Er is iets misgegaan.'): string {
  if (axios.isAxiosError(error)) {
    const detailMessage =
      typeof error.response?.data?.detail?.error?.message === 'string'
        ? error.response.data.detail.error.message
        : undefined
    const topLevelMessage =
      typeof error.response?.data?.error?.message === 'string'
        ? error.response.data.error.message
        : undefined

    return detailMessage ?? topLevelMessage ?? error.message ?? fallback
  }

  if (error instanceof Error && error.message) {
    return error.message
  }

  return fallback
}
