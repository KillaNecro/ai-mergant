import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Package, FileText, DollarSign, Wand2, Clock } from "lucide-react";

const StatCard = ({ label, value, icon: Icon, testid }) => (
  <div
    data-testid={testid}
    className="bg-white border border-slate-200 rounded-md shadow-sm p-6"
  >
    <div className="flex items-center justify-between">
      <div className="text-xs text-slate-500 font-medium uppercase tracking-widest">
        {label}
      </div>
      <Icon size={16} className="text-slate-400" strokeWidth={1.75} />
    </div>
    <div className="mt-3 text-2xl font-semibold text-[#0A1128] tracking-tight">
      {value}
    </div>
  </div>
);

const formatDate = (iso) => {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("tr-TR");
  } catch {
    return iso;
  }
};

const kindLabel = {
  import: "İçe Aktarma",
  edit: "Düzenleme",
  export: "Dışa Aktarma",
  bulk: "Toplu İşlem",
};

const Dashboard = () => {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.get("/dashboard/stats").then((r) => setStats(r.data));
  }, []);

  if (!stats) return <div className="text-slate-500">Yükleniyor...</div>;

  return (
    <div className="space-y-6" data-testid="dashboard-page">
      <div>
        <h1 className="text-2xl sm:text-3xl tracking-tight font-semibold text-[#0A1128]">
          Genel Bakış
        </h1>
        <p className="text-sm text-slate-600 mt-1">
          Katalog durumunuza dair özet bilgiler.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6">
        <StatCard label="Toplam Ürün" value={stats.total_products} icon={Package} testid="stat-total" />
        <StatCard label="Eksik Açıklama" value={stats.missing_description} icon={FileText} testid="stat-missing-desc" />
        <StatCard label="Eksik Fiyat" value={stats.missing_price} icon={DollarSign} testid="stat-missing-price" />
        <StatCard label="Düzenlenen Ürün" value={stats.edited_products} icon={Wand2} testid="stat-edited" />
      </div>

      <div className="bg-white border border-slate-200 rounded-md shadow-sm p-6">
        <div className="flex items-center gap-2 text-xs text-slate-500 uppercase tracking-widest">
          <Clock size={14} />
          Son İçe Aktarma
        </div>
        <div className="mt-2 text-base font-medium text-[#0A1128]">
          {formatDate(stats.last_import_at)}
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-md shadow-sm">
        <div className="px-6 py-4 border-b border-slate-200">
          <h2 className="text-lg font-semibold tracking-tight text-[#0A1128]">
            Son Aktiviteler
          </h2>
        </div>
        <ul data-testid="recent-activities" className="divide-y divide-slate-100">
          {stats.recent_activities.length === 0 && (
            <li className="px-6 py-8 text-sm text-slate-500">Henüz aktivite yok.</li>
          )}
          {stats.recent_activities.map((a) => (
            <li key={a.id} className="px-6 py-3 flex items-center justify-between text-sm">
              <div className="flex items-center gap-3">
                <span className="inline-flex items-center rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-600">
                  {kindLabel[a.kind] || a.kind}
                </span>
                <span className="text-slate-700">{a.message}</span>
              </div>
              <span className="text-xs text-slate-400">{formatDate(a.created_at)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

export default Dashboard;
