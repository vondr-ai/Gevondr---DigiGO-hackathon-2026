import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const STEPS = [
  { step: 1, name: 'setup-datasource', label: 'Databron' },
  { step: 2, name: 'setup-documents', label: 'Documenten & toegang' },
  { step: 3, name: 'setup-ai', label: 'AI' },
  { step: 4, name: 'setup-norms', label: 'Classificatie' },
  { step: 5, name: 'setup-delegations', label: 'Organisaties' },
  { step: 6, name: 'setup-overview', label: 'Overzicht' },
]

export function useStepNavigation() {
  const route = useRoute()
  const router = useRouter()

  const totalSteps = STEPS.length

  const currentStep = computed(() => {
    return (route.meta.step as number) ?? 1
  })

  const projectId = computed(() => route.params.id as string)

  function goToStep(step: number) {
    const target = STEPS.find((s) => s.step === step)
    if (target) {
      router.push({ name: target.name, params: { id: projectId.value } })
    }
  }

  function nextStep() {
    if (currentStep.value < totalSteps) goToStep(currentStep.value + 1)
  }

  function prevStep() {
    if (currentStep.value > 1) goToStep(currentStep.value - 1)
  }

  return { currentStep, totalSteps, projectId, goToStep, nextStep, prevStep, steps: STEPS }
}
