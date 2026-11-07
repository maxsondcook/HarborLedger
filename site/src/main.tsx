import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import "./styles.css";
import Home from "./pages/Home";
import Vessels from "./pages/Vessels";
import VesselPage from "./pages/VesselPage";
import Yards from "./pages/Yards";
import YardPage from "./pages/YardPage";
import Placeholder from "./pages/Placeholder";
import Ledger from "./pages/Ledger";
import Activity from "./pages/Activity";
import Encounters, { EncounterPage } from "./pages/Encounters";
import Methods from "./pages/Methods";
import Ocean from "./pages/Ocean";

function App() {
  const link = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : "");
  return (
    <>
      <header className="top">
        <div className="bar">
          <NavLink to="/" className="brand">HarborLedger</NavLink>
          <nav>
            <NavLink to="/vessels" className={link}>Vessels</NavLink>
            <NavLink to="/yards" className={link}>Shipyards</NavLink>
            <NavLink to="/ledger" className={link}>Repair ledger</NavLink>
            <NavLink to="/activity" className={link}>Harbor activity</NavLink>
            <NavLink to="/encounters" className={link}>Encounters</NavLink>
            <NavLink to="/ocean" className={link}>Weather &amp; fishing</NavLink>
            <NavLink to="/methods" className={link}>Methods</NavLink>
          </nav>
        </div>
      </header>
      <main className="shell">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/vessels" element={<Vessels />} />
          <Route path="/vessels/:slug" element={<VesselPage />} />
          <Route path="/yards" element={<Yards />} />
          <Route path="/yards/:slug" element={<YardPage />} />
          <Route path="/ledger" element={<Ledger />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="/encounters" element={<Encounters />} />
          <Route path="/encounters/:id" element={<EncounterPage />} />
          <Route path="/ocean" element={<Ocean />} />
          <Route path="/methods" element={<Methods />} />
          <Route path="*" element={<Placeholder title="Not found" />} />
        </Routes>
        <footer className="foot">
          Built from public data: USAspending, NOAA/BOEM MarineCadastre AIS, USCG PSIX and Merchant Vessels of
          the U.S., CalEPA SB 535 tracts, and Wikipedia ship lists (CC BY-SA). Every link shows its confidence
          and method. Not affiliated with any agency.
        </footer>
      </main>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </StrictMode>,
);
