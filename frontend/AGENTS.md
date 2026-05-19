# Frontend Agent Instructions

## UI quality standard

Every frontend UI task must follow the premium SaaS UI standard.

Before editing:
1. Inspect the existing component/page.
2. Identify why it looks generic, cluttered, weak, or AI-made.
3. Improve only the requested area.
4. Preserve behavior and data flow.

## Design principles

### 1. Layout first

Good UI comes from structure, not decoration.

Use:
- clear page headers
- obvious sections
- consistent spacing
- readable cards
- clean tables
- balanced density
- strong alignment

Avoid:
- random cards everywhere
- huge empty containers
- inconsistent gaps
- elements floating without a grid

### 2. Hierarchy

Every screen needs visual priority.

Use:
- strong title
- short subtitle/context
- primary action in one obvious place
- secondary actions less visually loud
- muted helper text
- badges only when meaningful

Avoid:
- everything same size
- too many equal-weight buttons
- decorative labels with no purpose

### 3. Premium SaaS styling

Use a dark professional interface.

Good:
- charcoal backgrounds
- dark maroon accents
- subtle borders
- calm hover states
- readable contrast
- polished forms and tables

Bad:
- rainbow gradients
- neon glow
- excessive blur
- generic AI glass cards
- huge gradient hero sections inside dashboard pages

### 4. Components

Buttons:
- clear primary / secondary / destructive hierarchy
- no random colors
- consistent radius and padding

Cards:
- subtle border
- controlled shadow
- useful header
- readable content
- no empty decorative cards

Tables:
- clean headers
- good row spacing
- readable actions
- useful empty state

Forms:
- grouped logically
- labels clear
- helper/error text readable
- inputs consistent

### 5. Motion

Motion is allowed only when it improves clarity.

Use:
- subtle hover
- short fade/slide
- small transform

Avoid:
- constant background movement
- floating blobs
- slow cinematic effects on admin pages
- animations that affect performance

## Responsive rules

Check desktop, tablet, and mobile layout mentally before finalizing.

On small screens:
- stack cards cleanly
- avoid horizontal overflow
- actions should wrap properly
- tables should remain usable or become card-like if already supported

## Validation

For frontend-only changes, run:

```bash
npm run build
```

Report:
- files changed
- visual improvements
- functionality preserved
- validation result
