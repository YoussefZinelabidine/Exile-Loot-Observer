<script lang="ts">
  import WhatToFarm from "./screens/WhatToFarm.svelte";
  import StashSearch from "./screens/StashSearch.svelte";
  import CheckItem from "./screens/CheckItem.svelte";
  import DataSettings from "./screens/DataSettings.svelte";

  const screens = [
    { id: "farm", label: "What to farm", component: WhatToFarm },
    { id: "stash", label: "Stash search", component: StashSearch },
    { id: "check", label: "Check an item", component: CheckItem },
    { id: "settings", label: "Data and settings", component: DataSettings },
  ] as const;

  type ScreenId = (typeof screens)[number]["id"];

  let current: ScreenId = $state("farm");
  const Current = $derived(screens.find((s) => s.id === current)!.component);
</script>

<div class="shell">
  <nav class="menu" aria-label="Main menu">
    <div class="brand">ELO</div>
    {#each screens as s (s.id)}
      <button
        type="button"
        class:active={current === s.id}
        aria-current={current === s.id ? "page" : undefined}
        onclick={() => (current = s.id)}
      >
        {s.label}
      </button>
    {/each}
  </nav>
  <main class="content">
    <Current />
  </main>
</div>

<style>
  .shell {
    display: flex;
    height: 100vh;
  }
  .menu {
    width: 220px;
    flex-shrink: 0;
    background: var(--surface);
    border-right: 1px solid var(--border);
    padding: 16px 12px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .brand {
    font-family: var(--font-heading);
    font-weight: 700;
    font-size: 20px;
    padding: 4px 12px 16px;
  }
  .menu button {
    background: transparent;
    color: var(--text-2);
    border: 1px solid transparent;
    border-radius: var(--radius-control);
    padding: 10px 12px;
    text-align: left;
    font: inherit;
    cursor: pointer;
  }
  .menu button:hover {
    background: var(--surface-input);
  }
  .menu button.active {
    background: var(--surface-input);
    border-color: var(--border-strong);
    color: var(--text);
  }
  .content {
    flex: 1;
    overflow: auto;
    padding: 24px 32px;
  }
</style>