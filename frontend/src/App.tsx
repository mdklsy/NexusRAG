import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Apps from "./pages/Apps";
import KnowledgeBases from "./pages/KnowledgeBases";
import KBDetail from "./pages/KBDetail";
import Playground from "./pages/Playground";
import Evals from "./pages/Evals";
import HumanLoop from "./pages/HumanLoop";
import Insights from "./pages/Insights";
import Users from "./pages/Users";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/apps" replace />} />
        <Route path="apps" element={<Apps />} />
        <Route path="kbs" element={<KnowledgeBases />} />
        <Route path="kbs/:kbId" element={<KBDetail />} />
        <Route path="playground" element={<Playground />} />
        <Route path="evals" element={<Evals />} />
        <Route path="hitl" element={<HumanLoop />} />
        <Route path="insights" element={<Insights />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="users" element={<Users />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/apps" replace />} />
    </Routes>
  );
}
