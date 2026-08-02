import React, { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { Search, Wand2, ChevronLeft, ChevronRight, AlertCircle } from "lucide-react";
import ProductEditor from "../components/ProductEditor";
import { toast } from "sonner";

const STATUS_LABELS = {
  imported: "İçe Aktarıldı",
  needs_attention: "Dikkat Gerekiyor",
  ready_for_ai: "AI İçin Hazır",
  awaiting_review: "İnceleme Bekliyor",
  approved: "Onaylandı",
  ready_to_publish: "Yayına Hazır",
};

const STATUS_TONE = {
  imported: "border-slate-200 bg-slate-50 text-slate-700",
  needs_attention: "border-red-200 bg-red-50 text-red-700",
  ready_for_ai: "border-blue-200 bg-blue-50 text-blue-700",
  awaiting_review: "border-amber-200 bg-amber-50 text-amber-700",
  approved: "border-emerald-200 bg-emerald-50 text-emerald-700",
  ready_to_publish: "border-emerald-300 bg-emerald-100 text-emerald-800",
};

const ScoreBadge = ({ score }) => {
  if (score == null) return <span className="text-slate-400 text-xs">—</span>;
  const tone =
    score >= 85 ? "bg-emerald-50 text-emerald-700 border-emerald-200"
    : score >= 60 ? "bg-amber-50 text-amber-700 border-amber-200"
    : "bg-red-50 text-red-700 border-red-200";
  return <span className={`inline-flex items-center rounded-full border ${tone} px-2 py-0.5 text-xs font-medium`}>{score}</span>;
};

const Products = () => {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [workflow, setWorkflow] = useState("");
  const [scoreBucket, setScoreBucket] = useState("");
  const [flags, setFlags] = useState({ missing_desc: false, missing_price: false, in_stock: false, edited: false });
  const [categories, setCategories] = useState([]);
  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState(new Set());
  const [editing, setEditing] = useState(null);
  const [exporting, setExporting] = useState(false);
  const pageSize = 15;

  const params = useMemo(() => {
    const p = { page, page_size: pageSize };
    if (q) p.q = q;
    if (category) p.category = category;
    if (workflow) p.workflow_status = workflow;
    if (scoreBucket) p.score_bucket = scoreBucket;
    Object.entries(flags).forEach(([k, v]) => { if (v) p[k] = true; });
    return p;
  }, [q, category, workflow, scoreBucket, flags, page]);

  const load = () => {
    setLoading(true); setError(null);
    api.get("/products", { params })
      .then((r) => setData(r.data))
      .catch((e) => setError(e?.response?.data?.detail || "Ürünler yüklenemedi"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [params]);
  useEffect(() => { api.get("/products/categories").then((r) => setCategories(r.data)).catch(() => {}); }, []);

  const toggle = (id) => {
    const s = new Set(selected);
    s.has(id) ? s.delete(id) : s.add(id);
    setSelected(s);
  };

  const pageIds = () => data.items.map((i) => i.id);
  const allPageSelected = data.items.length > 0 && data.items.every((i) => selected.has(i.id));
  const toggleAllPage = () => {
    const s = new Set(selected);
    if (allPageSelected) pageIds().forEach((id) => s.delete(id));
    else pageIds().forEach((id) => s.add(id));
    setSelected(s);
  };

  const exportSelected = async () => {
    if (selected.size === 0) return toast.error("Seçili ürün yok");
    if (exporting) return;
    setExporting(true);
    try {
      const res = await api.post("/export/selected", { ids: [...selected] }, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a"); a.href = url; a.download = "secili-urunler.csv"; a.click(); URL.revokeObjectURL(url);
      toast.success(`${selected.size} ürün dışa aktarıldı`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Dışa aktarma başarısız");
    } finally { setExporting(false); }
  };

  const totalPages = Math.max(1, Math.ceil(data.total / pageSize));

  return (
    <div className="space-y-6" data-testid="products-page">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl tracking-tight font-semibold text-[#0A1128]">Ürünler</h1>
          <p className="text-sm text-slate-600 mt-1">{data.total} ürün · {selected.size} seçili</p>
        </div>
        <button data-testid="export-selected-btn" onClick={exportSelected} disabled={exporting || selected.size === 0}
          className="bg-white border border-slate-200 hover:bg-slate-50 text-[#0A1128] rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50">
          {exporting ? "Aktarılıyor..." : "Seçilenleri Dışa Aktar"}
        </button>
      </div>

      <div className="bg-white border border-slate-200 rounded-md shadow-sm p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[240px]">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input data-testid="products-search" value={q}
              onChange={(e) => { setQ(e.target.value); setPage(1); }}
              placeholder="SKU veya ürün adı ara..."
              className="h-9 w-full rounded-md border border-slate-200 bg-white pl-9 pr-3 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-blue-500" />
          </div>
          <select data-testid="products-category-filter" value={category}
            onChange={(e) => { setCategory(e.target.value); setPage(1); }}
            className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-blue-500">
            <option value="">Tüm Kategoriler</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select data-testid="products-workflow-filter" value={workflow}
            onChange={(e) => { setWorkflow(e.target.value); setPage(1); }}
            className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-blue-500">
            <option value="">Tüm Durumlar</option>
            {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select data-testid="products-score-filter" value={scoreBucket}
            onChange={(e) => { setScoreBucket(e.target.value); setPage(1); }}
            className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-blue-500">
            <option value="">Tüm Skorlar</option>
            <option value="low">Skor &lt; 60</option>
            <option value="mid">Skor 60–84</option>
            <option value="high">Skor ≥ 85</option>
            <option value="critical">Kritik Sorunlu</option>
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {[
            ["missing_desc", "Eksik Açıklama"],
            ["missing_price", "Eksik Fiyat"],
            ["in_stock", "Stokta Olanlar"],
            ["edited", "Düzenlenenler"],
          ].map(([k, label]) => (
            <label key={k} className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
              <input type="checkbox" data-testid={`filter-${k}`} checked={flags[k]}
                onChange={(e) => { setFlags({ ...flags, [k]: e.target.checked }); setPage(1); }}
                className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
              {label}
            </label>
          ))}
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-md shadow-sm overflow-hidden">
        <table className="w-full text-sm text-left border-collapse">
          <thead>
            <tr className="bg-slate-50 text-slate-600 font-medium border-y border-slate-200">
              <th className="px-4 py-3 w-10">
                <input type="checkbox" data-testid="select-all" title="Bu sayfayı seç"
                  checked={allPageSelected} onChange={toggleAllPage}
                  className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
              </th>
              <th className="px-4 py-3 w-16">Görsel</th>
              <th className="px-4 py-3">SKU</th>
              <th className="px-4 py-3">Ürün Adı</th>
              <th className="px-4 py-3">Kategori</th>
              <th className="px-4 py-3">Fiyat</th>
              <th className="px-4 py-3">Stok</th>
              <th className="px-4 py-3">Kalite</th>
              <th className="px-4 py-3">Sorun</th>
              <th className="px-4 py-3">Durum</th>
              <th className="px-4 py-3 text-right">İşlemler</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={11} className="px-4 py-10 text-center text-slate-500">Yükleniyor...</td></tr>
            )}
            {!loading && error && (
              <tr><td colSpan={11} className="px-4 py-10 text-center">
                <div className="inline-flex items-center gap-2 text-red-700"><AlertCircle size={16} /> {error}</div>
                <div className="mt-2"><button onClick={load} className="text-sm font-medium text-blue-700">Tekrar dene</button></div>
              </td></tr>
            )}
            {!loading && !error && data.items.length === 0 && (
              <tr><td colSpan={11} className="px-4 py-10 text-center text-slate-500">Kayıt bulunamadı.</td></tr>
            )}
            {!loading && !error && data.items.map((p) => (
              <tr key={p.id} className="border-b border-slate-100 hover:bg-slate-50/60 text-slate-700">
                <td className="px-4 py-3">
                  <input type="checkbox" data-testid={`row-select-${p.sku}`} checked={selected.has(p.id)}
                    onChange={() => toggle(p.id)}
                    className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
                </td>
                <td className="px-4 py-3">
                  {p.image_url ? <img src={p.image_url} alt="" className="w-10 h-10 rounded object-cover border border-slate-200" />
                    : <div className="w-10 h-10 rounded bg-slate-100 border border-slate-200" />}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-slate-500">{p.sku}</td>
                <td className="px-4 py-3">
                  <div className="font-medium text-[#0A1128] line-clamp-1">{p.name}</div>
                </td>
                <td className="px-4 py-3">{p.category || <span className="text-slate-400">-</span>}</td>
                <td className="px-4 py-3">{p.price != null ? `₺${Number(p.price).toLocaleString("tr-TR", { minimumFractionDigits: 2 })}` : <span className="text-amber-600">-</span>}</td>
                <td className="px-4 py-3">{p.stock ?? 0}</td>
                <td className="px-4 py-3"><ScoreBadge score={p.quality_score} /></td>
                <td className="px-4 py-3 text-xs">{p.issue_count > 0 ? <span className="font-medium text-amber-700">{p.issue_count}</span> : <span className="text-slate-400">0</span>}</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_TONE[p.workflow_status] || STATUS_TONE.imported}`}>
                    {p.workflow_status_label || STATUS_LABELS[p.workflow_status] || p.workflow_status}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <button data-testid={`edit-btn-${p.sku}`} onClick={() => setEditing(p.id)}
                    className="inline-flex items-center gap-1 text-sm font-medium text-blue-700 hover:text-blue-800">
                    <Wand2 size={14} /> Düzenle
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex items-center justify-between px-4 py-3 border-t border-slate-200 bg-slate-50/50 text-sm text-slate-600">
          <div>Sayfa {page} / {totalPages} · <span className="text-slate-400">Tümü Seç yalnızca bu sayfayı seçer</span></div>
          <div className="flex items-center gap-2">
            <button data-testid="prev-page" disabled={page <= 1 || loading} onClick={() => setPage(page - 1)}
              className="px-2 py-1 rounded border border-slate-200 bg-white disabled:opacity-50"><ChevronLeft size={14} /></button>
            <button data-testid="next-page" disabled={page >= totalPages || loading} onClick={() => setPage(page + 1)}
              className="px-2 py-1 rounded border border-slate-200 bg-white disabled:opacity-50"><ChevronRight size={14} /></button>
          </div>
        </div>
      </div>

      {editing && <ProductEditor productId={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
    </div>
  );
};

export default Products;
