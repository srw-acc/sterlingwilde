# Walkthrough 20260512-143027 — Agent Context Cartridge

UI elements referenced repeatedly:
- Create Segment modal (`m0001`, `m0002`, `m0003`)
- Save button in Create Segment modal (`m0002`, `m0003`)
- Dashboard empty state (`m0000`)
- 'segment scope' dropdown (`m0001`)

Screens referenced:
- Dashboard (empty state)
- Create Segment modal

---

### [high] Save action has no in-flight feedback

- kind: ux_friction
- what's happening: Save button takes ~3s, no spinner / disabled state / toast; user can't tell if it worked.
- evidence: m0002, m0003
- direction: disable Save on click, show spinner, toast on success, error inline on failure

### [medium] Empty dashboard offers no guidance

- kind: ux_friction
- what's happening: First-time user lands on empty dashboard, no copy or CTA explaining what to do.
- evidence: m0000
- direction: add empty-state component pointing to the Create flow

### [medium] 'Segment scope' field is undocumented

- kind: ux_friction
- what's happening: Create Segment modal has a 'segment scope' dropdown with two options and no help text.
- evidence: m0001
- direction: add inline tooltip / help text differentiating the two options

---

## Suggested grep targets

- `CreateSegment` or `SegmentModal`
- `segment_scope` / `segmentScope`
- Dashboard empty-state component (look for `EmptyState`, `useDashboardData` hook returning empty)
- The Save handler in the Create Segment form — check whether it disables the button or sets a loading state.
