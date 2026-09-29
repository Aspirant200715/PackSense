// Run before the body is parsed so a returning visitor never sees the welcome screen.
try {
  const snapshot = JSON.parse(localStorage.getItem("packsense.workspace.v1"));
  if (snapshot?.version === 1 && snapshot.entered === true) {
    document.documentElement.dataset.workspaceRestore = "pending";
  }
} catch { /* The app will start with the welcome screen if storage is unavailable. */ }
