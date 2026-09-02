# Frontend

The current operator console is plain HTML, CSS, and JavaScript. FastAPI serves
this directory at `/` and `/static`; no separate frontend development server is
required.

Files:

- `index.html` — page structure
- `styles.css` — presentation
- `app.js` — API calls and UI state

Validate JavaScript from the repository root:

```bash
node --check frontend/app.js
```
