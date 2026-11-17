/**
 * The title of the meeting that was just opened from a list. The meeting page shows it while its
 * data loads, so the title is on screen in the same render as the navigation and can travel there
 * as a shared element instead of fading in once the data arrives.
 */
const titles = new Map<string, string>()

export function rememberMeeting(id: string, title: string) {
  titles.set(id, title)
}

export function recallMeeting(id: string): string | undefined {
  return titles.get(id)
}
