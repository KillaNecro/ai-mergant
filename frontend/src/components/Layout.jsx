import React, { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import { api } from "../lib/api";
import { Toaster } from "sonner";

const Layout = () => {
  const [demoMode, setDemoMode] = useState(false);

  useEffect(() => {
    api.get("/health").then((r) => setDemoMode(!!r.data?.demo_mode)).catch(() => {});
  }, []);

  return (
    <div className="flex h-screen w-full overflow-hidden text-[#0A1128]">
      <Sidebar />
      <div className="flex-1 flex flex-col h-screen overflow-y-auto">
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b border-slate-200/80 bg-white/80 backdrop-blur px-6 supports-[backdrop-filter]:bg-white/60">
          <div className="text-sm font-medium text-slate-500">
            AI Destekli Ürün Kataloğu Yönetimi
          </div>
          {demoMode && (
            <span
              data-testid="demo-mode-badge"
              className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-[11px] font-semibold text-amber-700 tracking-wide uppercase"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
              Demo Modu
            </span>
          )}
        </header>
        <main className="p-6 md:p-8 max-w-7xl w-full flex-1 space-y-6">
          <Outlet />
        </main>
      </div>
      <Toaster position="top-right" richColors />
    </div>
  );
};

export default Layout;
