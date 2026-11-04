import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import type { EngineClient } from "./lib/engine";
import { SessionProvider, useSession } from "./lib/session";
import { JobsProvider } from "./lib/jobs";
import { ToastProvider } from "./components/Toast";
import { Splash, EngineDown } from "./screens/Splash";
import { SignIn } from "./screens/SignIn";
import { OnboardingWizard } from "./screens/onboarding/Wizard";
import { Layout } from "./components/Layout";
import { Dashboard } from "./screens/Dashboard";
import { Professors } from "./screens/Professors";
import { Replies } from "./screens/Replies";
import { Conversations } from "./screens/Conversations";
import { Pipeline } from "./screens/Pipeline";
import { Jobs } from "./screens/Jobs";
import { SettingsScreen } from "./screens/Settings";

function Gate() {
  const { status, user, onboarding } = useSession();
  if (status === "loading" && !user) return <Splash />;
  if (status === "error") return <EngineDown />;
  if (!user) return <SignIn />;
  if (!onboarding.done) return <OnboardingWizard />;
  return (
    <JobsProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="professors" element={<Professors />} />
          <Route path="replies" element={<Replies />} />
          <Route path="conversations" element={<Conversations />} />
          <Route path="pipeline" element={<Pipeline />} />
          <Route path="jobs" element={<Jobs />} />
          <Route path="jobs/:id" element={<Jobs />} />
          <Route path="settings" element={<SettingsScreen />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Routes>
    </JobsProvider>
  );
}

export default function App({ engine }: { engine?: EngineClient }) {
  return (
    <ToastProvider>
      <SessionProvider engine={engine}>
        <HashRouter>
          <Gate />
        </HashRouter>
      </SessionProvider>
    </ToastProvider>
  );
}
