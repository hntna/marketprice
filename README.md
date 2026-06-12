# Bảng giá — Vàng · BTC · Dầu · USD/VND

Dashboard nhìn nhanh chạy hoàn toàn trên GitHub Pages, không cần server:

- **Tầng trực tiếp (browser → Binance):** BTC/USDT và PAXG/USDT (proxy XAU/USD) qua WebSocket, nhảy theo giây.
- **Tầng cron (GitHub Actions, 15 phút/lần):** vàng Bảo Tín Mạnh Hải (qua giavang.org), tỷ giá USD Vietcombank, dầu Brent/WTI → ghi `prices.json`, trang đọc file tĩnh.
- **Chỉ số phái sinh:** chênh lệch vàng trong nước − thế giới quy đổi, tính trực tiếp trên trang
  theo công thức `XAUUSD × tỷ giá bán VCB × 1,20565` (1 lượng = 37,5 g ÷ 31,1035 g/oz).

## Cài đặt (5 phút)

1. Tạo repo mới (ví dụ `bang-gia`), đẩy toàn bộ thư mục này lên nhánh `main`
   (giữ nguyên cấu trúc, đặc biệt là `.github/workflows/update-prices.yml`).
2. **Settings → Pages** → Source: *Deploy from a branch* → `main` / `(root)`.
3. **Settings → Actions → General** → Workflow permissions: chọn **Read and write permissions** → Save.
4. Vào tab **Actions** → workflow **Cập nhật giá** → bấm **Run workflow** chạy lần đầu.
5. Mở `https://<username>.github.io/bang-gia/` — xong.

## Cấu trúc

```
index.html                          # dashboard (tự đọc prices.json + Binance)
prices.json                         # dữ liệu tầng cron (bot tự commit đè)
scripts/fetch_prices.py             # script fetch 3 nguồn "chậm"
.github/workflows/update-prices.yml # cron 15 phút + commit
```

## Ghi chú vận hành

- Cron của GitHub Actions chạy theo giờ UTC và **có thể trễ vài phút** lúc cao điểm — bình thường.
- Nguồn nào lỗi thì script **giữ giá cũ và gắn cờ `stale`** (trang hiện badge "CŨ"), không bao giờ bịa số;
  nếu cả 3 nguồn cùng lỗi thì giữ nguyên file cũ, không commit.
- Trang chính thức baotinmanhhai.vn chặn truy cập tự động, nên dùng trang tổng hợp
  giavang.org (đã kèm tên nguồn + giờ niêm yết trong dữ liệu).
- Bot commit ~96 lần/ngày vào `prices.json`. Lâu lâu muốn gọn lịch sử thì squash,
  hoặc giảm tần suất trong dòng `cron`.
- Repo public không có hoạt động nào trong 60 ngày có thể bị GitHub tắt scheduled workflow —
  vào Actions bật lại là chạy tiếp.

## Đổi nguồn / mở rộng

- Tỷ giá tự do, sparkline lịch sử (đã có sẵn `history` trong `prices.json`), cảnh báo giá…
  đều có thể đắp thêm mà không đổi kiến trúc.
- Muốn theo dõi thêm cặp Binance nào, sửa danh sách symbol trong `index.html`
  (hàm `seedBinance` và `connectWS`).

*Số liệu chỉ để tham khảo cá nhân, không phải khuyến nghị đầu tư.*
