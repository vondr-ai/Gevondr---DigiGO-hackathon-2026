import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Project } from '@/types'
import * as projectsApi from '@/api/projects'

export const useProjectsStore = defineStore('projects', () => {
  const items = ref<Project[]>([])
  const loading = ref(false)

  async function fetchProjects() {
    loading.value = true
    try {
      const res = await projectsApi.listProjects()
      items.value = res.items
    } finally {
      loading.value = false
    }
  }

  async function createProject(name: string, description?: string) {
    const project = await projectsApi.createProject({ name, description })
    items.value.push(project)
    return project
  }

  async function deleteProject(id: string) {
    await projectsApi.deleteProject(id)
    items.value = items.value.filter((p) => p.id !== id)
  }

  return { items, loading, fetchProjects, createProject, deleteProject }
})
