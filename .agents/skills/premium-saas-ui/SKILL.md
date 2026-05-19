---
name: premium-saas-ui
description: Use this skill when improving React/TypeScript frontend UI, admin dashboard pages, SaaS product screens, onboarding flows, settings pages, tables, cards, forms, empty states, responsive polish, or when the user says the UI looks generic, AI-made, sloppy, or like AI slop.
---

# Premium SaaS UI Skill

## Purpose

Transform existing UI into a polished SaaS admin dashboard style without breaking functionality.

This skill is for UI improvement only. It must not change backend behavior, API contracts, auth logic, tenant logic, routing logic, database logic, or payload shapes.

## Before coding

Inspect the requested area and answer internally:

1. What is the purpose of this screen?
2. What is the primary action?
3. What information matters most?
4. What looks generic or AI-made?
5. What can be improved with layout, spacing, typography, and hierarchy before adding decoration?

## Anti-slop rules

Do not use:
- random gradient backgrounds
- giant glowing blobs
- overdone glassmorphism
- decorative cards with little content
- mismatched border radii
- inconsistent spacing
- too many accent colors
- fake AI dashboard visuals
- animations that constantly move
- landing-page hero sections inside admin screens

## Visual target

The UI should feel like:
- Linear
- Vercel dashboard
- Stripe dashboard
- Supabase dashboard
- Retool
- Clerk
- Resend
- Attio

Use these as quality references, not as brands to copy.

## Preferred style

- dark charcoal / black base
- deep maroon accent
- subtle borders
- soft but controlled shadows
- readable text contrast
- balanced density
- enterprise SaaS feel
- calm hover states
- practical, clean information layout

## Improvement order

Always improve in this order:

1. Layout structure
2. Spacing
3. Alignment
4. Typography
5. Information hierarchy
6. Component consistency
7. Empty/loading/error states
8. Responsive behavior
9. Subtle visual polish
10. Motion, only if useful

Do not start with gradients or animations.

## Component rules

### Page headers

A good page header includes:
- clear title
- short subtitle
- one main action if needed
- optional stats/context

Avoid oversized headers that waste space.

### Cards

Cards must have a purpose.

Each card should have:
- title or label
- useful content
- clear hierarchy
- consistent padding
- subtle border

### Tables/lists

Tables and lists should be:
- readable
- aligned
- scannable
- not cramped
- not overly empty

Important rows/actions should be easy to find.

### Forms

Forms should:
- group related fields
- use clear labels
- show helper text where useful
- keep actions fixed or easy to find
- make destructive actions visually distinct

### Empty states

Empty states should:
- explain what is missing
- tell the user what to do next
- avoid cartoonish decoration

## Responsive polish

For every UI change, consider:
- desktop
- tablet
- mobile

Avoid:
- horizontal overflow
- tiny action buttons
- broken wrapping
- huge cards stacked awkwardly

## Functional safety

Preserve:
- API calls
- hooks
- state names where possible
- prop shapes
- auth flow
- tenant headers
- routing
- forms
- event handlers
- existing business logic

Do not introduce new dependencies unless explicitly approved.

## Required final report

After finishing, report:

1. Files changed
2. What looked weak before
3. What was improved visually
4. What functionality was preserved
5. Validation command and result
6. Any remaining UI weakness worth fixing next
