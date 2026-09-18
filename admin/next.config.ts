import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  // Ancla el tracing de salida a este paquete: evita el warning de
  // «workspace root inferred» cuando hay otros lockfiles en $HOME (Termux).
  outputFileTracingRoot: path.join(__dirname),
};

export default nextConfig;
