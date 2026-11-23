# ELO app (Tauri v2 + Svelte 5 + TypeScript)

Owner: frontend and overlay agent.

## Run

```
pnpm install
pnpm tauri dev
```

Other scripts: `pnpm check` (svelte-check + tsc), `pnpm build` (Vite build), `pnpm test` (Vitest).

## Licences

The item parser (added in a later phase) is meant to reuse code from Awakened PoE Trade, which is MIT-licensed. The licence notice must be kept with any copied code. Do not copy code from poe.re or poe-vendor-string (AGPL-3.0).
## Windows build prerequisites

- Rust stable (with cargo).
- Visual Studio Build Tools with the "Desktop development with C++" workload, including a Windows SDK.
- WebView2 runtime (preinstalled on current Windows 10/11).

## Notes

TypeScript is pinned to 5.9 because svelte-check has not been verified against TypeScript 7.
