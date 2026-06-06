import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import X402Lab from "./pages/X402Lab";
import PitchDeck from "./pages/PitchDeck";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="x402-lab" element={<X402Lab />} />
        <Route path="pitch" element={<PitchDeck />} />
      </Route>
    </Routes>
  );
}
