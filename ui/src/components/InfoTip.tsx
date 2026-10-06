import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { clsx } from 'clsx'
import { Info } from 'lucide-react'
import { GLOSSARY, type GlossaryKey } from '../lib/glossary'

// A small ⓘ button with a one-line definition from the glossary. Shown on hover and on keyboard focus, toggled
// by a tap on touch screens; hidden on mouse leave, blur and Escape. Place it next to a <label>, never inside
// one, so it does not become part of an input's accessible name. It never submits a form and its clicks do not
// reach clickable parents (table rows, cards).

type Side = 'top' | 'bottom'
type Align = 'start' | 'center' | 'end'

const TIP_WIDTH = 290 // the tooltip's max width, plus a margin
const ROOM_BELOW = 110 // enough for a few lines of text
const ALIGN: Record<Align, string> = {
  start: '-left-1',
  center: 'left-1/2 -translate-x-1/2',
  end: '-right-1',
}

// The area the tooltip must fit in: the viewport, narrowed by any ancestor that clips its overflow (a scrolling
// table or panel).
function visibleBounds(element: HTMLElement) {
  let top = 0
  let left = 0
  let bottom = window.innerHeight
  let right = window.innerWidth
  for (let node = element.parentElement; node && node !== document.body; node = node.parentElement) {
    const { overflowX, overflowY } = window.getComputedStyle(node)
    if (overflowX === 'visible' && overflowY === 'visible') continue
    const rect = node.getBoundingClientRect()
    top = Math.max(top, rect.top)
    left = Math.max(left, rect.left)
    bottom = Math.min(bottom, rect.bottom)
    right = Math.min(right, rect.right)
  }
  return { top, left, bottom, right }
}

// Below the icon unless there is clearly more room above. It runs rightwards from the icon, or leftwards when the
// icon is near a right edge, and is centred only when neither side has room.
function placement(button: HTMLElement): { side: Side; align: Align } {
  const rect = button.getBoundingClientRect()
  const bounds = visibleBounds(button)
  const below = bounds.bottom - rect.bottom
  const above = rect.top - bounds.top
  return {
    side: below >= ROOM_BELOW || below >= above ? 'bottom' : 'top',
    align: bounds.right - rect.left >= TIP_WIDTH ? 'start' : rect.right - bounds.left >= TIP_WIDTH ? 'end' : 'center',
  }
}

export default function InfoTip({ term, label, className }: { term: GlossaryKey; label?: string; className?: string }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [where, setWhere] = useState<{ side: Side; align: Align }>({ side: 'bottom', align: 'center' })
  const wrapper = useRef<HTMLSpanElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  // The pointer type of the press in progress: a touch press toggles on tap instead of opening on focus.
  const pressedWith = useRef<string | null>(null)

  const show = useCallback(() => {
    if (button.current) setWhere(placement(button.current))
    setOpen(true)
  }, [])
  const hide = useCallback(() => setOpen(false), [])

  // While open, Escape anywhere (e.g. when only hovered) or a press outside closes it.
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    const onPress = (event: PointerEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPress)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPress)
    }
  }, [open])

  const name = label ?? term.replace(/_/g, ' ')

  // Hover is handled on the wrapper, so moving the mouse onto the tooltip keeps it open.
  return (
    <span
      ref={wrapper}
      className={clsx('relative inline-flex shrink-0 align-middle', className)}
      onPointerEnter={(event) => {
        if (event.pointerType !== 'touch') show()
      }}
      onPointerLeave={(event) => {
        if (event.pointerType !== 'touch') hide()
      }}
    >
      <button
        ref={button}
        type="button"
        aria-label={`What is ${name}?`}
        aria-describedby={open ? id : undefined}
        className="inline-flex cursor-help items-center justify-center rounded-full p-0.5 text-slate-500 transition-colors hover:text-zen-600 focus-visible:text-zen-600"
        onPointerDown={(event) => {
          pressedWith.current = event.pointerType
        }}
        onFocus={() => {
          if (pressedWith.current !== 'touch') show()
        }}
        onBlur={() => {
          pressedWith.current = null
          hide()
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && open) {
            event.stopPropagation() // closes the tip only, not a dialog around it
            hide()
          }
        }}
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
          const touch = pressedWith.current === 'touch'
          pressedWith.current = null
          if (touch && open) hide()
          else show()
        }}
      >
        <Info size={14} aria-hidden />
      </button>
      {open && (
        <span
          className={clsx(
            'absolute z-50',
            where.side === 'bottom' ? 'top-full pt-1.5' : 'bottom-full pb-1.5',
            ALIGN[where.align],
          )}
        >
          <span
            role="tooltip"
            id={id}
            className="block w-max max-w-[min(280px,calc(100vw-32px))] whitespace-normal rounded-lg bg-slate-900 px-2.5 py-1.5 text-left text-[12.5px] font-normal normal-case leading-snug tracking-normal text-white shadow-xl"
          >
            {GLOSSARY[term]}
          </span>
        </span>
      )}
    </span>
  )
}
