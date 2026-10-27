/**
 * Progressive enhancement for the URL-paste form (Story 1.9, AD-10).
 *
 * The form's `action="/"`/`method="get"` keeps working exactly as before
 * (Story 1.8's no-JS fallback) when this script never runs or fails to
 * load. When it does run, submitting the form instead:
 *   1. `preventDefault()`s the normal full-page GET.
 *   2. `fetch`es `GET /jobs?url=...` for a `job_id`.
 *   3. Opens `new EventSource('/jobs/' + job_id + '/events')`.
 *   4. Updates `#progress` on each `stage` event.
 *   5. On the `result` event, renders the verdict/insufficient-data result
 *      into `#result-mount` -- mirroring `index.html`'s own field choices
 *      (label, confidence + evidence basis, pros/cons + citations,
 *      alternatives) -- then closes the connection.
 *
 * Not unit-tested here: there is no browser/JS runtime in this project's
 * test environment (pytest-only). The server-side SSE endpoint this script
 * consumes is fully tested via `TestClient` (see `tests/test_main.py`).
 */

(function () {
    "use strict";

    var STAGE_LABELS = {
        resolving_product: "Resolving the product page…",
        sampling_reviews: "Sampling reviews…",
        finding_alternatives: "Finding alternatives…",
        synthesizing_verdict: "Synthesizing the verdict…"
    };

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function stageLabel(stage) {
        return STAGE_LABELS[stage] || stage;
    }

    function renderProsConsList(items, emptyText) {
        if (!items || items.length === 0) {
            return '<p class="empty">' + escapeHtml(emptyText) + "</p>";
        }
        var html = '<ul>';
        items.forEach(function (item) {
            html +=
                "<li>" +
                '<p class="claim">' + escapeHtml(item.text) + "</p>" +
                '<p class="citation">Source: &ldquo;' +
                escapeHtml(item.citation.quote) +
                "&rdquo; (" +
                escapeHtml(item.citation.source_type) +
                ")</p>" +
                "</li>";
        });
        html += "</ul>";
        return html;
    }

    function renderAlternatives(alternatives) {
        if (!alternatives || alternatives.length === 0) {
            return '<p class="empty">No alternatives were found.</p>';
        }
        var html = '<ul>';
        alternatives.forEach(function (alt) {
            html += "<li>" + escapeHtml(alt.title);
            if (alt.price !== null && alt.price !== undefined) {
                html += " &mdash; $" + Number(alt.price).toFixed(2);
            }
            html += "</li>";
        });
        html += "</ul>";
        return html;
    }

    function renderInsufficientData(result) {
        var html =
            '<section class="result result--insufficient_data">' +
            "<h2>Insufficient data</h2>" +
            '<p class="reason">Reason: ' + escapeHtml(result.reason) + "</p>";
        if (result.detail) {
            html += '<p class="detail">' + escapeHtml(result.detail) + "</p>";
        }
        if (result.source_tier) {
            html +=
                '<p class="source-tier">Source tier attempted: ' +
                escapeHtml(result.source_tier) +
                "</p>";
        }
        html += "</section>";
        return html;
    }

    function renderVerdict(result, resultKind) {
        var basis = result.evidence_basis;
        var html =
            '<section class="result result--' + escapeHtml(resultKind) + '">' +
            '<h2 class="label label--' +
            escapeHtml(String(result.label).toLowerCase()) +
            '">' +
            escapeHtml(result.label) +
            "</h2>" +
            '<p class="confidence">Confidence: ' +
            Math.round(result.confidence * 100) +
            "% &mdash; based on " +
            basis.review_count +
            " review(s)" +
            (basis.is_low_signal ? " (low review signal)" : "") +
            ", " +
            basis.alternatives_count +
            " alternative(s) found, via " +
            escapeHtml(basis.source_tier) +
            " source.";
        if (resultKind === "low_confidence") {
            html +=
                ' <span class="low-confidence-flag">This is a low-confidence verdict.</span>';
        }
        html += "</p>";
        html += '<p class="reasoning-summary">' + escapeHtml(result.reasoning_summary) + "</p>";
        html += "<h3>Pros</h3>" + renderProsConsList(result.pros, "No pros were resolvable from the evidence.");
        html += "<h3>Cons</h3>" + renderProsConsList(result.cons, "No cons were resolvable from the evidence.");
        html += "<h3>Alternatives</h3>" + renderAlternatives(result.alternatives);
        html += "</section>";
        return html;
    }

    function renderResult(resultKind, result) {
        var mount = document.getElementById("result-mount");
        if (!mount) {
            return;
        }
        mount.innerHTML =
            resultKind === "insufficient_data"
                ? renderInsufficientData(result)
                : renderVerdict(result, resultKind);
    }

    function setupForm() {
        var form = document.querySelector("form.url-form");
        var progressEl = document.getElementById("progress");
        var resultMount = document.getElementById("result-mount");
        if (!form || typeof window.EventSource === "undefined" || typeof window.fetch === "undefined") {
            return;
        }

        // Tracks the in-flight job's `EventSource`, if any, so a resubmit
        // can close it before opening a new one -- otherwise a slower first
        // job's result could arrive after and overwrite a faster second
        // job's already-rendered result, and the first job's connection
        // would be left open indefinitely.
        var currentSource = null;

        form.addEventListener("submit", function (event) {
            var input = form.querySelector("#url");
            var url = input ? input.value : "";
            if (!url) {
                return;
            }

            event.preventDefault();

            if (currentSource) {
                currentSource.close();
                currentSource = null;
            }

            // Clear any server-rendered `.result` section left over from a
            // prior full-page `GET /?url=...` load -- otherwise it stays
            // visible alongside (or instead of) the new `#result-mount`
            // content this handler is about to render.
            document.querySelectorAll(".result").forEach(function (el) {
                el.remove();
            });

            if (progressEl) {
                progressEl.textContent = "Starting…";
            }
            if (resultMount) {
                resultMount.innerHTML = "";
            }

            fetch("/jobs?url=" + encodeURIComponent(url))
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error("Failed to create job");
                    }
                    return response.json();
                })
                .then(function (data) {
                    var jobId = data.job_id;
                    var source = new EventSource("/jobs/" + jobId + "/events");
                    currentSource = source;

                    source.addEventListener("stage", function (messageEvent) {
                        var payload = JSON.parse(messageEvent.data);
                        if (progressEl) {
                            progressEl.textContent = stageLabel(payload.stage);
                        }
                    });

                    source.addEventListener("result", function (messageEvent) {
                        var payload = JSON.parse(messageEvent.data);
                        if (progressEl) {
                            progressEl.textContent = "";
                        }
                        renderResult(payload.result_kind, payload.result);
                        source.close();
                        if (currentSource === source) {
                            currentSource = null;
                        }
                    });

                    source.onerror = function () {
                        // Deliberately does not `close()` the source: a
                        // transient network blip should let `EventSource`'s
                        // own native reconnect proceed rather than
                        // permanently abandoning the progress/result display
                        // while the job keeps running server-side.
                        if (progressEl) {
                            progressEl.textContent =
                                "Lost connection to the progress stream. Retrying…";
                        }
                    };
                })
                .catch(function () {
                    if (progressEl) {
                        progressEl.textContent = "Could not start the job. Try again.";
                    }
                });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", setupForm);
    } else {
        setupForm();
    }
})();
