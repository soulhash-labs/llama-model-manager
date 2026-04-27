export interface LifecycleState {
  parentPid: number | null;
  active: boolean;
  lastCheckAt: string | null;
}

const TEN_SECONDS = 10_000;

export function startLifecycleGuard(onExit: () => void): LifecycleState {
  const state: LifecycleState = {
    parentPid: process.ppid || null,
    active: true,
    lastCheckAt: null,
  };

  const check = () => {
    state.lastCheckAt = new Date().toISOString();
    const parentPid = process.ppid;
    if (state.parentPid !== null && parentPid !== state.parentPid) {
      state.parentPid = parentPid;
    }

    if (!state.parentPid || state.parentPid <= 0) {
      state.active = false;
      onExit();
      return;
    }

    try {
      process.kill(state.parentPid, 0);
    } catch {
      state.active = false;
      onExit();
    }
  };

  setInterval(check, 30_000).unref();
  setTimeout(check, TEN_SECONDS).unref();
  return state;
}
