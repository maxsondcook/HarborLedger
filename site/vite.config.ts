import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served from https://<user>.github.io/HarborLedger/ on GitHub Pages.
export default defineConfig({
  base: "/HarborLedger/",
  plugins: [react()],
});
