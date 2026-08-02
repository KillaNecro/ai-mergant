import React from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard, Package, Upload, Layers, Download, Settings as SettingsIcon,
} from "lucide-react";

const items = [
  { to: "/", label: "Genel Bakış", icon: LayoutDashboard, testid: "nav-dashboard" },
  { to: "/urunler", label: "Ürünler", icon: Package, testid: "nav-products" },
  { to: "/ice-aktar", label: "İçe Aktar", icon: Upload, testid: "nav-import" },
  { to: "/toplu", label: "Toplu İşlemler", icon: Layers, testid: "nav-bulk" },
  { to: "/disa-aktar", label: "Dışa Aktar", icon: Download, testid: "nav-export" },
  { to: "/ayarlar", label: "Ayarlar", icon: SettingsIcon, testid: "nav-settings" },
];

const Sidebar = () => {
  return (
    <aside
      data-testid="sidebar"
      className="w-64 bg-white border-r border-slate-200/80 flex flex-col h-full flex-shrink-0"
    >
      <div className="h-14 flex items-center px-5 border-b border-slate-200/80">
        <div className="flex items-center gap-2.5">
          <div className="relative w-8 h-8 rounded-lg bg-[#0A1128] flex items-center justify-center text-white text-[13px] font-bold shadow-sm">
            <span className="tracking-tight">M</span>
            <span className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-blue-500 ring-2 ring-white" />
          </div>
          <div className="leading-tight">
            <div className="font-bold text-[15px] text-[#0A1128] tracking-tight">Merchant OS</div>
            <div className="text-[10px] uppercase tracking-[0.16em] text-slate-400 font-semibold">Lite</div>
          </div>
        </div>
      </div>

      <div className="px-5 py-4">
        <div className="text-[10px] uppercase tracking-[0.14em] text-slate-400 font-semibold mb-2">Menü</div>
      </div>

      <nav className="flex-1 px-3 space-y-0.5">
        {items.map((it) => {
          const Icon = it.icon;
          return (
            <NavLink
              key={it.to}
              to={it.to}
              end={it.to === "/"}
              data-testid={it.testid}
              className={({ isActive }) =>
                (isActive
                  ? "relative flex items-center gap-3 px-3 py-2 rounded-md text-sm font-semibold text-[#0A1128] bg-blue-50/70"
                  : "relative flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium text-slate-500 hover:text-[#0A1128] hover:bg-slate-100/70") +
                " group transition-colors"
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span aria-hidden className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full bg-blue-600" />
                  )}
                  <Icon
                    size={16}
                    strokeWidth={isActive ? 2 : 1.75}
                    className={isActive ? "text-blue-600" : "text-slate-400 group-hover:text-slate-600"}
                  />
                  <span>{it.label}</span>
                </>
              )}
            </NavLink>
          );
        })}
      </nav>

      <div className="p-4 border-t border-slate-200/80 mt-4">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          <span className="text-[11px] text-slate-500 font-medium">Sistem aktif</span>
        </div>
        <div className="mt-1 text-[11px] text-slate-400">v1.0 · MVP</div>
      </div>
    </aside>
  );
};

export default Sidebar;
