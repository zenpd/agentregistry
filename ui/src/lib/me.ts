import { useEffect, useState } from 'react'
import { getMe } from '../services/api'

// The signed-in person and what their role allows. Fetched once per page load
// and shared, so every screen hides the same actions the server would refuse.
export interface Me {
  user_id: string
  role: string
  name: string | null
  email: string | null
  accountRole: string | null
  perms: string[]
  gates: string[]
  rbac: boolean
  awayUntil: string | null
  deputyUserId: string | null
}

let cached: Promise<Me | null> | null = null

export function loadMe(): Promise<Me | null> {
  if (!cached) cached = getMe().then(r => r.data as Me).catch(() => { cached = null; return null })
  return cached
}

export function useMe(): Me | null {
  const [me, setMe] = useState<Me | null>(null)
  useEffect(() => { let live = true; loadMe().then(m => { if (live) setMe(m) }); return () => { live = false } }, [])
  return me
}

// After a change to the signed-in person (away period), so the next read is fresh.
export function reloadMe(): Promise<Me | null> {
  cached = null
  return loadMe()
}

export const can = (me: Me | null, perm: string) => !!me && me.perms.includes(perm)
export const canDecide = (me: Me | null, gate: string) => !!me && me.gates.includes(gate)

// The sentence shown instead of an action the role does not allow.
export function notAllowed(me: Me | null, what: string): string {
  return `Your role${me?.accountRole ? `, ${me.accountRole},` : ''} cannot ${what}.`
}
