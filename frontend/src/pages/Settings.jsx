import React, { useEffect, useState } from "react";
import { api } from "../lib/api";

const Settings = () => {
  const [health, setHealth] = useState(null);
  useEffect(() => { api.get("/health").then((r) => setHealth(r.data)); }, []);
  return (
    <div className="space-y-6" data-testid="settings-page">
      <div>
        <h1 className="text-2xl sm:text-3xl tracking-tight font-semibold text-[#0A1128]">Ayarlar</h1>
        <p className="text-sm text-slate-600 mt-1">Uygulama ve entegrasyon bilgileri.</p>
      </div>
      <div className="bg-white border border-slate-200 rounded-md shadow-sm p-6 space-y-4">
        <Row label="Uygulama Adı" value="AI Merchant OS Lite" />
        <Row label="Sürüm" value="1.0.0 · MVP" />
        <Row label="AI Modu" value={health?.demo_mode ? "Demo Modu (API anahtarı tanımlı değil)" : "Gemini Etkin"} />
        <Row label="Veritabanı" value="SQLite" />
      </div>
      <div className="bg-white border border-slate-200 rounded-md shadow-sm p-6">
        <div className="text-xs text-slate-500 uppercase tracking-widest">AI Anahtarı</div>
        <p className="text-sm text-slate-700 mt-2">
          Gemini kullanmak için <code className="text-xs bg-slate-100 px-1 py-0.5 rounded">backend/.env</code> dosyasına
          {" "}<code className="text-xs bg-slate-100 px-1 py-0.5 rounded">GEMINI_API_KEY</code> ekleyin ve backend&apos;i yeniden başlatın.
        </p>
      </div>
    </div>
  );
};

const Row = ({ label, value }) => (
  <div className="flex items-center justify-between border-b border-slate-100 pb-3 last:border-b-0 last:pb-0">
    <div className="text-sm text-slate-500">{label}</div>
    <div className="text-sm font-medium text-[#0A1128]">{value}</div>
  </div>
);

export default Settings;
