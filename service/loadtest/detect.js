// k6 load test for POST /v1/detect: a closed loop of VUS virtual users, each
// posting one sample image (multipart) and waiting for the answer.
//
// Environment:
//   BASE_URL     service URL (default http://127.0.0.1:8000)
//   IMAGE        image file, relative to this script (default ../tests/data/samples/site-backs.webp)
//   VUS          concurrent virtual users (default 4)
//   DURATION     run length (default 20s)
//   KEEPALIVE    "1" (default) reuses connections; "0" opens a new connection per request
//   P95_MS       if set, the run fails when p95 latency exceeds it (CI gate)
//   MAX_ERR      allowed error ratio for the gate (default 0.01)
//   SUMMARY      if set, write a compact JSON summary to this path
//   LABEL        free text copied into the summary
import http from 'k6/http';
import { check } from 'k6';

const IMAGE = __ENV.IMAGE || '../tests/data/samples/site-backs.webp';
const img = open(IMAGE, 'b');
const BASE = __ENV.BASE_URL || 'http://127.0.0.1:8000';
const KEEPALIVE = (__ENV.KEEPALIVE || '1') !== '0';

const thresholds = {};
if (__ENV.P95_MS) {
  thresholds.http_req_duration = [`p(95)<${__ENV.P95_MS}`];
  thresholds.http_req_failed = [`rate<${__ENV.MAX_ERR || '0.01'}`];
}

export const options = {
  vus: Number(__ENV.VUS || 4),
  duration: __ENV.DURATION || '20s',
  noConnectionReuse: !KEEPALIVE,
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  thresholds,
};

export default function () {
  const res = http.post(`${BASE}/v1/detect`, {
    file: http.file(img, IMAGE.split('/').pop(), 'image/webp'),
  });
  check(res, { 'status is 200': (r) => r.status === 200 });
}

export function handleSummary(data) {
  const m = data.metrics;
  const d = m.http_req_duration.values;
  const statuses = {};
  const out = {
    label: __ENV.LABEL || '',
    vus: options.vus,
    duration: options.duration,
    keepalive: KEEPALIVE,
    image: IMAGE.split('/').pop(),
    requests: m.http_reqs.values.count,
    throughput_rps: m.http_reqs.values.rate,
    error_rate: m.http_req_failed ? m.http_req_failed.values.rate : 0,
    checks_passed: m.checks ? m.checks.values.passes : 0,
    checks_failed: m.checks ? m.checks.values.fails : 0,
    latency_ms: {
      avg: d.avg, min: d.min, p50: d.med, p90: d['p(90)'], p95: d['p(95)'], p99: d['p(99)'], max: d.max,
    },
    thresholds_ok: Object.values(data.metrics).every(
      (x) => !x.thresholds || Object.values(x.thresholds).every((t) => t.ok),
    ),
  };
  const files = { stdout: JSON.stringify(out) + '\n' };
  if (__ENV.SUMMARY) files[__ENV.SUMMARY] = JSON.stringify(out, null, 1) + '\n';
  return files;
}
