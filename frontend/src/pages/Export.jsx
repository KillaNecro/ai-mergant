import React, { useEffect, useState } from "react";
import { api, API_BASE } from "../lib/api";
import { Download } from "lucide-react";
import { toast } from "sonner";

const ExportPage = () => {
  const [categories, setCategories] = useState([]);
  const [filters, setFilters] = useState({
    q: "",
    category: "",
    missing_desc: false,
    missing_price: false,
    in_stock: false,
    edited: false,
  });

  useEffect(() => { api.get("/products/categories").then((r) => setCategories(r.data)); }, []);

  const download = async (blob, name) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  };

  const exportAll = async () => {
    const res = await api.get("/export/all", { responseType: "blob" });
    download(res.data, "tum-urunler.csv");
    toast.success("Tüm ürünler indirildi");
  };

  const exportFiltered = async () => {
    const params = {};
    Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
    const res = await api.get("/export/filtered", { params, responseType: "blob" });
    download(res.data, "filtrelenmis-urunler.csv");
    toast.success("Filtreli ürünler indirildi");
  };

  return (
    <div className="space-y-6" data-testid="export-page">
      <div>
        <h1 className="text-2xl sm:text-3xl tracking-tight font-semibold text-[#0A1128]">Dışa Aktar</h1>
        <p className="text-sm text-slate-600 mt-1">UTF-8 CSV formatında, Türkçe karakter uyumlu.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white border border-slate-200 rounded-md shadow-sm p-6">
          <div className="text-xs text-slate-500 uppercase tracking-widest">Hızlı Dışa Aktar</div>
          <h2 className="text-lg font-semibold tracking-tight text-[#0A1128] mt-2">Tüm Ürünler</h2>
          <p className="text-sm text-slate-600 mt-1">Katalogdaki tüm ürünleri tek dosyada indirin.</p>
          <button
            data-testid="export-all-btn"
            onClick={exportAll}
            className="mt-5 inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md px-4 py-2 text-sm font-medium"
          >
            <Download size={14} /> Tümünü İndir
          </button>
        </div>

        <div className="bg-white border border-slate-200 rounded-md shadow-sm p-6">
          <div className="text-xs text-slate-500 uppercase tracking-widest">Filtreli Dışa Aktar</div>
          <h2 className="text-lg font-semibold tracking-tight text-[#0A1128] mt-2">Kriterlere Göre</h2>
          <div className="mt-4 space-y-3">
            <input
              value={filters.q}
              onChange={(e) => setFilters({ ...filters, q: e.target.value })}
              placeholder="Arama..."
              data-testid="export-q"
              className="w-full h-9 rounded-md border border-slate-200 bg-white px-3 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <select
              value={filters.category}
              onChange={(e) => setFilters({ ...filters, category: e.target.value })}
              data-testid="export-category"
              className="w-full h-9 rounded-md border border-slate-200 bg-white px-3 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">Tüm Kategoriler</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <div className="grid grid-cols-2 gap-2 text-sm">
              {[
                ["missing_desc", "Eksik Açıklama"],
                ["missing_price", "Eksik Fiyat"],
                ["in_stock", "Stokta Olanlar"],
                ["edited", "Düzenlenenler"],
              ].map(([k, label]) => (
                <label key={k} className="flex items-center gap-2 text-slate-700">
                  <input type="checkbox" checked={filters[k]} data-testid={`export-${k}`}
                    onChange={(e) => setFilters({ ...filters, [k]: e.target.checked })}
                    className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
                  {label}
                </label>
              ))}
            </div>
          </div>
          <button
            data-testid="export-filtered-btn"
            onClick={exportFiltered}
            className="mt-5 inline-flex items-center gap-2 bg-white border border-slate-200 hover:bg-slate-50 text-[#0A1128] rounded-md px-4 py-2 text-sm font-medium"
          >
            <Download size={14} /> Filtreli İndir
          </button>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-md shadow-sm p-6">
        <div className="text-xs text-slate-500 uppercase tracking-widest">Örnek Şablon</div>
        <h2 className="text-lg font-semibold tracking-tight text-[#0A1128] mt-2">İçe Aktarma İçin Örnek CSV</h2>
        <p className="text-sm text-slate-600 mt-1">Şablonu indirin ve kendi ürünlerinizi ekleyerek İçe Aktar sayfasından yükleyin.</p>
        <a
          data-testid="export-sample-link"
          href={`${API_BASE}/import/sample`}
          className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-blue-700 hover:text-blue-800"
        >
          <Download size={14} /> Örnek CSV İndir
        </a>
      </div>
    </div>
  );
};

export default ExportPage;
