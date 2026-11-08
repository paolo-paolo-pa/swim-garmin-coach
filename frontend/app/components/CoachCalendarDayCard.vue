<!-- Adapted from watt-mind/coach CoachCalendarDayCard.vue, Apache-2.0. Modified: local plans and Garmin load, no synthetic readiness/TSS, confirmed changes instead of drag-and-drop. -->
<template>
  <div
    class="min-h-[132px] rounded-2xl border border-default/70 bg-default p-3 transition"
    :class="[
      compact ? 'min-h-[100px] p-2.5' : '',
      isToday ? 'ring-2 ring-primary/50' : '',
      ''
    ]"
  >
    <div class="flex items-start justify-between gap-2">
      <button type="button" class="text-left" @click="$emit('day-click')">
        <div class="text-[10px] font-black uppercase tracking-[0.18em] text-muted">
          {{ formatDateUTC(date, compact ? 'EEE' : 'EEEE') }}
        </div>
        <div class="text-lg font-black text-highlighted">
          {{ formatDateUTC(date, compact ? 'd' : 'MMM d') }}
        </div>
      </button>

    </div>

    <div
      v-if="daySummary"
      class="mt-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-muted"
    >
      
      <span v-if="daySummary">{{ daySummary.plannedCount }} piani · {{ daySummary.completedCount }} eseguite</span>
    </div>

    <div class="mt-3 space-y-2">
      <button
        v-for="activity in visibleActivities"
        :key="activity.id"
        class="group relative w-full rounded-xl border px-2 py-1.5 text-left text-xs transition hover:bg-default/80"
        :class="activityClass(activity)"
        @click="
          () => {
            void $emit('activity-click', activity)
          }
        "
      >
        <div class="flex items-start gap-2">
          <div class="mt-1 h-2 w-2 shrink-0 rounded-full" :class="activityDotClass(activity)" />
          <div class="min-w-0 flex-1">
            <div class="truncate font-bold">{{ activity.title }}</div>
            <div class="mt-0.5 flex items-center gap-1 text-[10px] text-muted">
              <span>{{ activity.type || 'Allenamento' }}</span>
              <span v-if="activity.distance_m != null"> · {{ Number(activity.distance_m).toLocaleString('it-IT') }} m</span>
            </div>

            <div
              v-if="activity.source === 'completed' && activity.plannedWorkoutId"
              class="mt-1 inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[9px] font-black uppercase tracking-wider text-primary"
            >
              <UIcon name="i-lucide-calendar" class="h-3 w-3" />
              Piano collegato
            </div>

            <div
              v-else-if="activity.source === 'planned' && activity.status === 'completed_plan'"
              class="mt-1 inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[9px] font-black uppercase tracking-wider text-primary"
            >
              <UIcon name="i-lucide-circle-check" class="h-3 w-3" />
              Eseguito
            </div>

            <div
              v-if="activity.linkedPlannedWorkout"
              class="mt-1 text-[10px] font-medium italic text-primary/80"
            >
              {{ activity.linkedPlannedWorkout.title }}
            </div>
          </div>
        </div>
      </button>

      <button @click="$emit('day-click')"
        v-if="hiddenCount > 0"
        class="rounded-xl border border-dashed border-default/80 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-muted"
      >
        +{{ hiddenCount }} altre · apri giorno
      </button>

      <button @click="$emit('day-click')"
        v-if="!visibleActivities.length"
        class="rounded-xl border border-dashed border-default/70 px-2 py-3 text-center text-[10px] font-bold uppercase tracking-wider text-muted/60"
      >
        Apri il giorno
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
  type CalendarActivity = Record<string, any>

  const props = defineProps<{
    date: Date
    activities: CalendarActivity[]
    daySummary?: any
    compact?: boolean
    isToday?: boolean
  }>()

  const emit = defineEmits<{
    'day-click': []
    'activity-click': [activity: CalendarActivity]
  }>()

  const { formatDateUTC } = useFormat()

  const visibleActivities = computed(() => props.activities.slice(0, props.compact ? 3 : 6))
  const hiddenCount = computed(() =>
    Math.max(0, props.activities.length - visibleActivities.value.length)
  )

  function activityClass(activity: CalendarActivity) {
    if (
      (activity.source === 'completed' && activity.plannedWorkoutId) ||
      (activity.source === 'planned' && activity.status === 'completed_plan')
    ) {
      return 'border-blue-200 bg-blue-50 dark:border-blue-900/30 dark:bg-blue-950/20'
    }
    if (activity.source === 'planned') {
      return activity.status === 'cancelled'
        ? 'border-red-200 bg-red-50 dark:border-red-900/30 dark:bg-red-950/20'
        : 'border-amber-200 bg-amber-50 dark:border-amber-900/30 dark:bg-amber-950/20'
    }
    if (activity.source === 'completed') {
      return 'border-emerald-200 bg-emerald-50 dark:border-emerald-900/30 dark:bg-emerald-950/20'
    }
    return 'border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-gray-900/70'
  }

  function activityDotClass(activity: CalendarActivity) {
    if (
      (activity.source === 'completed' && activity.plannedWorkoutId) ||
      (activity.source === 'planned' && activity.status === 'completed_plan')
    ) {
      return 'bg-blue-500'
    }
    if (activity.source === 'planned') {
      return activity.status === 'cancelled' ? 'bg-red-500' : 'bg-amber-500'
    }
    if (activity.source === 'completed') {
      return 'bg-emerald-500'
    }
    return 'bg-gray-400'
  }

</script>
