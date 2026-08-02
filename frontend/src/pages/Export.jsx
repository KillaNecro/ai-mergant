import React, { useEffect, useState } from "react";
import { api, API_BASE } from "../lib/api";
import { Download, AlertCircle, Rocket } from "lucide-react";
import { toast } from "sonner";

const ExportPage = () => {
  const [categories, setCategories] = useState([]);
  const [busyKind, setBusyKind] = useState("");
  const [filters, setFilters] = useState({
    q: "", category: "",
    missing_desc: false, missing_price: false, in_stock: false, edited: false,
  });

  useEffect(() => {
    api.get("/products/categories").then((r) => setCategories(r.data)).catch(() => {});
  }, []);

  const download = (blob, name) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  };

  const exportAll = async () => {
    if (busyKind) return;
    setBusyKind("all");
    try {
      const res = await api.get("/export/all", { responseType: "blob" });
      download(res.data, "tum-urunler.csv");
      toast.success("Tüm ürünler indirildi");
    } catch (e) { toast.error(e?.response?.data?.detail || "Dışa aktarma başarısız"); }
    finally { setBusyKind(""); }
  };

  const exportFiltered = async () => {
    if (busyKind) return;
    setBusyKind("filtered");
    try {
      const params = {};
      Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
      const res = await api.get("/export/filtered", { params, responseType: "blob" });
      download(res.data, "filtrelenmis-urunler.csv");
      toast.success("Filtreli ürünler indirildi");
    } catch (e) { toast.error(e?.response?.data?.detail || "Dışa aktarma başarısız"); }
    finally { setBusyKind(""); }
  };

  const exportReady = async () => {
    if (busyKind) return;
    setBusyKind("ready");
    try {
      const res = await api.get("/export/ready-to-publish", { responseType: "blob" });
      download(res.data, "yayina-hazir-urunler.csv");
      toast.success("Yayına hazır ürünler indirildi");
    } catch (e) { toast.error(e?.response?.data?.detail || "Dışa aktarma başarısız"); }
    finally { setBusyKind(""); }
  };

  return (
    <div className="space-y-6" data-testid="export-page">
      <div>
        <h1 className="text-2xl sm:text-3xl tracking-tight font-semibold text-[#0A1128]">Dışa Aktar</h1>
        <p className="text-sm text-slate-600 mt-1">UTF-8 CSV formatında, Türkçe karakter uyumlu.</p>
      </div>

      <div className="bg-white border border-emerald-200 rounded-md shadow-sm p-6" data-testid="ready-to-publish-card">
        <div className="flex items-center gap-2 text-xs text-emerald-700 uppercase tracking-widest font-semibold">
          <Rocket size={14} /> Yayına Hazır
        </div>
        <h2 className="text-lg font-semibold tracking-tight text-[#0A1128] mt-2">Yayına Hazır Ürünleri Dışa Aktar</h2>
        <p className="text-sm text-slate-600 mt-1">
          Yalnızca onaylı ve nihai doğrulamayı geçmiş ürünleri, SEO başlığı, meta açıklama ve etiketlerle birlikte indirir.
        </p>
        <button data-testid="export-ready-btn" onClick={exportReady} disabled={busyKind === "ready"}
          className="mt-5 inline-flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-md px-4 py-2 text-sm font-medium disabled:opacity-60">
          <Download size={14} /> {busyKind === "ready" ? "Hazırlanıyor..." : "Yayına Hazır Ürünleri İndir"}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white border border-slate-200 rounded-md shadow-sm p-6">
          <div className="text-xs text-slate-500 uppercase tracking-widest">Tüm Katalog</div>
          <h2 className="text-lg font-semibold tracking-tight text-[#0A1128] mt-2">Tüm Ürünler</h2>
          <p className="text-sm text-slate-600 mt-1">Katalogdaki tüm ürünleri tek dosyada indirin (orijinal alanlar).</p>
          <button data-testid="export-all-btn" onClick={exportAll} disabled={busyKind === "all"}
            className="mt-5 inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md px-4 py-2 text-sm font-medium disabled:opacity-60">
            <Download size={14} /> {busyKind === "all" ? "Hazırlanıyor..." : "Tümünü İndir"}
          </button>
        </div>

        <div className="bg-white border border-slate-200 rounded-md shadow-sm p-6">
          <div className="text-xs text-slate-500 uppercase tracking-widest">Filtreli Dışa Aktar</div>
          <h2 className="text-lg font-semibold tracking-tight text-[#0A1128] mt-2">Kriterlere Göre</h2>
          <div className="mt-4 space-y-3">
            <input value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })}
              placeholder="Arama..." data-testid="export-q"
              className="w-full h-9 rounded-md border border-slate-200 bg-white px-3 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500" />
            <select value={filters.category} onChange={(e) => setFilters({ ...filters, category: e.target.value })}
              data-testid="export-category"
              className="w-full h-9 rounded-md border border-slate-200 bg-white px-3 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500">
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
          <button data-testid="export-filtered-btn" onClick={exportFiltered} disabled={busyKind === "filtered"}
            className="mt-5 inline-flex items-center gap-2 bg-white border border-slate-200 hover:bg-slate-50 text-[#0A1128] rounded-md px-4 py-2 text-sm font-medium disabled:opacity-60">
            <Download size={14} /> {busyKind === "filtered" ? "Hazırlanıyor..." : "Filtreli İndir"}
          </button>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-md shadow-sm p-6">
        <div className="text-xs text-slate-500 uppercase tracking-widest">Örnek Şablon</div>
        <h2 className="text-lg font-semibold tracking-tight text-[#0A1128] mt-2">İçe Aktarma İçin Örnek CSV</h2>
        <p className="text-sm text-slate-600 mt-1">Şablonu indirin ve kendi ürünlerinizi ekleyerek İçe Aktar sayfasından yükleyin.</p>
        <a data-testid="export-sample-link" href={`${API_BASE}/import/sample`}
          className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-blue-700 hover:text-blue-800">
          <Download size={14} /> Örnek CSV İndir
        </a>
      </div>
    </div>
  );
};

export default ExportPage;
