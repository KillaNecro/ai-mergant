import React from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Package,
  Upload,
  Layers,
  Download,
  Settings as SettingsIcon,
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
      className="w-64 bg-[#F9FAFB] border-r border-slate-200 flex flex-col h-full flex-shrink-0"
    >
      <div className="h-14 flex items-center px-5 border-b border-slate-200">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-blue-600 flex items-center justify-center text-white text-xs font-bold">
            M
          </div>
          <div className="font-semibold text-[#0A1128] tracking-tight text-sm">
            Merchant OS
          </div>
        </div>
      </div>
      <nav className="flex-1 p-3 space-y-1">
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
                  ? "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium text-blue-700 bg-blue-50"
                  : "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium text-slate-600 hover:text-[#0A1128] hover:bg-slate-100") +
                " transition-colors"
              }
            >
              <Icon size={16} strokeWidth={1.75} />
              <span>{it.label}</span>
            </NavLink>
          );
        })}
      </nav>
      <div className="p-4 text-xs text-slate-400 border-t border-slate-200">
        v1.0 · MVP
      </div>
    </aside>
  );
};

export default Sidebar;
