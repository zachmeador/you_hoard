/** @import { IconName } from './icons.js' */

/** @type {{ key: 'library' | 'subscriptions' | 'queue' | 'system', label: string, short: string, icon: IconName }[]} */
export const NAV = [
  { key: 'library', label: 'Library', short: 'Library', icon: 'shelf' },
  { key: 'subscriptions', label: 'Subscriptions', short: 'Subs', icon: 'feed' },
  { key: 'queue', label: 'Queue', short: 'Queue', icon: 'queue' },
  { key: 'system', label: 'System', short: 'System', icon: 'sliders' }
]
