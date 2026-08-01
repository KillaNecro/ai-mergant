import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { toast } from "sonner";
import { Sparkles, Tags, TrendingUp, TrendingDown, Download } from "lucide-react";

const BulkOps = () => {
  const [products, setProducts] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [categories, setCategories] = useState([]);
  const [newCategory, setNewCategory] = useState("");
  const [pct, setPct] = useState(10);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");

  const load = () => api.get("/products", { params: { page_size: 200, q: q || undefined } }).then((r) => setProducts(r.data.items));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [q]);
  useEffect(() => { api.get("/products/categories").then((r) => setCategories(r.data)); }, []);

  const toggle = (id) => {
    const s = new Set(selected);
    s.has(id) ? s.delete(id) : s.add(id);
    setSelected(s);
  };

  const toggleAll = () => {
    if (products.every((p) => selected.has(p.id))) setSelected(new Set());
    else setSelected(new Set(products.map((p) => p.id)));
  };

  const requireSelected = () => {
    if (selected.size === 0) { toast.error("Önce ürün seçin"); return false; }
    return true;
  };

  const run = async (fn, successMsg) => {
    if (!requireSelected()) return;
    setBusy(true);
    try {
      await fn();
      toast.success(successMsg);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "İşlem başarısız");
    } finally { setBusy(false); }
  };

  const ids = () => [...selected];

  const improveTitles = () => run(() => api.post("/bulk/improve-products", { ids: ids(), kind: "title" }), "Başlıklar iyileştirildi");
  const improveDescs = () => run(() => api.post("/bulk/improve-products", { ids: ids(), kind: "description" }), "Açıklamalar iyileştirildi");
  const setCat = () => {
    if (!newCategory.trim()) return toast.error("Kategori girin");
    run(() => api.post("/bulk/category", { ids: ids(), category: newCategory.trim() }), "Kategori güncellendi");
  };
  const priceUp = () => run(() => api.post("/bulk/price-percent", { ids: ids(), percent: Math.abs(Number(pct)) }), "Fiyat arttırıldı");
  const priceDown = () => run(() => api.post("/bulk/price-percent", { ids: ids(), percent: -Math.abs(Number(pct)) }), "Fiyat düşürüldü");

  const exportSel = async () => {
    if (!requireSelected()) return;
    const res = await api.post("/export/selected", { ids: ids() }, { responseType: "blob" });
    downloadBlob(res.data, "secili-urunler.csv");
    toast.success("Dışa aktarıldı");
  };

  return (
    <div className="space-y-6" data-testid="bulk-page">
      <div>
        <h1 className="text-2xl sm:text-3xl tracking-tight font-semibold text-[#0A1128]">Toplu İşlemler</h1>
        <p className="text-sm text-slate-600 mt-1">Ürünleri seçin, tek tıkla toplu güncelleyin.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <ActionCard title="AI ile Başlık İyileştir" icon={Sparkles} onClick={improveTitles} testid="bulk-improve-titles" disabled={busy} />
        <ActionCard title="AI ile Açıklama İyileştir" icon={Sparkles} onClick={improveDescs} testid="bulk-improve-descs" disabled={busy} />
        <ActionCard title="Seçilenleri Dışa Aktar" icon={Download} onClick={exportSel} testid="bulk-export" disabled={busy} />
        <div className="bg-white border border-slate-200 rounded-md shadow-sm p-5 space-y-3">
          <div className="flex items-center gap-2 text-sm font-medium text-[#0A1128]"><Tags size={16} /> Kategori Ata</div>
          <input list="cats" value={newCategory} onChange={(e) => setNewCategory(e.target.value)}
            placeholder="Örn. Elektronik" data-testid="bulk-category-input"
            className="w-full h-9 rounded-md border border-slate-200 bg-white px-3 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500" />
          <datalist id="cats">{categories.map((c) => <option key={c} value={c} />)}</datalist>
          <button data-testid="bulk-category-apply" disabled={busy} onClick={setCat}
            className="w-full bg-blue-600 hover:bg-blue-700 text-white rounded-md px-3 py-2 text-sm font-medium disabled:opacity-60">Uygula</button>
        </div>
        <div className="bg-white border border-slate-200 rounded-md shadow-sm p-5 space-y-3">
          <div className="flex items-center gap-2 text-sm font-medium text-[#0A1128]"><TrendingUp size={16} /> Fiyat Yüzdesi</div>
          <div className="flex items-center gap-2">
            <input type="number" value={pct} onChange={(e) => setPct(e.target.value)} data-testid="bulk-pct-input"
              className="flex-1 h-9 rounded-md border border-slate-200 bg-white px-3 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500" />
            <span className="text-sm text-slate-500">%</span>
          </div>
          <div className="flex gap-2">
            <button data-testid="bulk-price-up" disabled={busy} onClick={priceUp}
              className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded-md px-3 py-2 text-sm font-medium disabled:opacity-60 inline-flex items-center justify-center gap-1">
              <TrendingUp size={14} /> Arttır
            </button>
            <button data-testid="bulk-price-down" disabled={busy} onClick={priceDown}
              className="flex-1 bg-slate-700 hover:bg-slate-800 text-white rounded-md px-3 py-2 text-sm font-medium disabled:opacity-60 inline-flex items-center justify-center gap-1">
              <TrendingDown size={14} /> Düşür
            </button>
          </div>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-md shadow-sm">
        <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between gap-4">
          <div className="text-sm font-medium text-[#0A1128]">Ürünler ({products.length}) — {selected.size} seçili</div>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ara..."
            className="h-8 rounded-md border border-slate-200 px-3 text-sm w-64 focus:outline-none focus:ring-1 focus:ring-blue-500"
            data-testid="bulk-search" />
        </div>
        <div className="max-h-[520px] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-slate-50 text-slate-600 border-b border-slate-200">
              <tr>
                <th className="px-4 py-2 w-10 text-left">
                  <input type="checkbox" data-testid="bulk-select-all"
                    checked={products.length > 0 && products.every((p) => selected.has(p.id))}
                    onChange={toggleAll}
                    className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
                </th>
                <th className="px-4 py-2 text-left font-medium">SKU</th>
                <th className="px-4 py-2 text-left font-medium">Ürün Adı</th>
                <th className="px-4 py-2 text-left font-medium">Kategori</th>
                <th className="px-4 py-2 text-left font-medium">Fiyat</th>
                <th className="px-4 py-2 text-left font-medium">Stok</th>
              </tr>
            </thead>
            <tbody>
              {products.map((p) => (
                <tr key={p.id} className="border-b border-slate-100 hover:bg-slate-50/60">
                  <td className="px-4 py-2">
                    <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggle(p.id)}
                      data-testid={`bulk-row-${p.sku}`}
                      className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500" />
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-slate-500">{p.sku}</td>
                  <td className="px-4 py-2 text-[#0A1128]">{p.improved_name || p.name}</td>
                  <td className="px-4 py-2 text-slate-700">{p.category || "-"}</td>
                  <td className="px-4 py-2 text-slate-700">{p.price != null ? `₺${Number(p.price).toLocaleString("tr-TR", { minimumFractionDigits: 2 })}` : "-"}</td>
                  <td className="px-4 py-2 text-slate-700">{p.stock ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

const ActionCard = ({ title, icon: Icon, onClick, testid, disabled }) => (
  <button
    data-testid={testid}
    onClick={onClick}
    disabled={disabled}
    className="bg-white border border-slate-200 rounded-md shadow-sm p-5 text-left hover:border-blue-300 hover:bg-blue-50/30 transition-colors disabled:opacity-60"
  >
    <Icon size={18} className="text-blue-600" strokeWidth={1.75} />
    <div className="mt-3 text-sm font-medium text-[#0A1128]">{title}</div>
    <div className="mt-1 text-xs text-slate-500">Seçili ürünlere uygulanır</div>
  </button>
);

function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  URL.revokeObjectURL(url);
}

export default BulkOps;
