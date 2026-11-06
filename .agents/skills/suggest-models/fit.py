#!/usr/bin/env python3
"""suggest-models fit calculator: will a candidate model fit, and roughly how fast is it?

Pure arithmetic (standard library only); it reads nothing from the network. The
inputs come from the research step (model card / GGUF header) and from this
machine's measured numbers.

Memory (GiB):   footprint = weights + KV cache + compute overhead
  KV per token  = kv_layers x kv_heads x kv_dim x bytes_per_element
                  kv_dim = key head dim + value head dim; only full-attention
                  layers count for hybrid models (e.g. 1 in 4 for Qwen3.6/3.8).
  Same formula as the notes in models.ini. It is COMPUTED, not measured: the
  router's startup log ("needs on Vulkan0: N MiB") is the real figure, and has
  been 2-4 GiB below this estimate for the presets measured so far.

Discrete GPU (--vram-gib): KV and compute stay in VRAM; weights that don't fit
  spill to system RAM (partial -ngl, or --n-cpu-moe for MoE experts). The spill
  must fit in --budget-gib (system RAM for models), and decode is estimated as
  time = gpu_bytes / --bandwidth-gbs + cpu_bytes / --ram-bandwidth-gbs per token.
  Expert offload on MoE models usually beats this proportional split.
  Without --vram-gib, memory is unified (Apple silicon, Strix Halo): one pool.

Decode speed:   bandwidth-bound ceiling = bandwidth / bytes read per token, where
  bytes per token = active parameters x bits per weight / 8. AGENTS.md notes decode
  here is NOT purely weight-bandwidth bound, so the ceiling overestimates. Give a
  measured reference of the same architecture family (--ref-active-gb, --ref-tps)
  and the estimate scales from it instead: tps = ref_tps x ref_active_gb / active_gb.
  Treat any result as a rough range, not a prediction.

Usage examples:
  python fit.py --name Qwen3.6-35B-A3B-Q4 --weights-gib 20.8 \\
      --kv-layers 10 --kv-heads 2 --kv-dim 512 --ctx 262144 \\
      --active-b 3 --bpw 5 --ref-active-gb 1.9 --ref-tps 60 \\
      --budget-gib 96 --bandwidth-gbs 256
  python fit.py ... --resident 26 25        # other models staying loaded (GiB)
  python fit.py ... --vram-gib 24 --bandwidth-gbs 1000 --ram-bandwidth-gbs 90 --budget-gib 48
  python fit.py ... --json
"""
import argparse, json, sys

KV_BYTES = {"f16": 2.0, "bf16": 2.0, "q8_0": 34 / 32, "q4_0": 18 / 32}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="candidate")
    ap.add_argument("--weights-gib", type=float, help="GGUF size on disk (all shards + mmproj if used)")
    ap.add_argument("--params-b", type=float, help="total parameters (billions), if file size unknown")
    ap.add_argument("--bpw", type=float, help="average bits per weight of the quant (e.g. 4.8 for Q4_K_M)")
    ap.add_argument("--kv-layers", type=int, help="number of FULL-attention layers")
    ap.add_argument("--kv-heads", type=int)
    ap.add_argument("--kv-dim", type=int, help="key head dim + value head dim")
    ap.add_argument("--ctx", type=int, default=32768, help="total context (c), all slots together")
    ap.add_argument("--kv-type", default="f16", choices=sorted(KV_BYTES))
    ap.add_argument("--compute-gib", type=float, default=3.0, help="compute buffers (default 3)")
    ap.add_argument("--budget-gib", type=float, required=True,
                    help="memory budget for weights+KV, GiB (see local/AGENTS.md)")
    ap.add_argument("--resident", type=float, nargs="*", default=[],
                    help="footprints (GiB) of models that stay loaded alongside")
    ap.add_argument("--active-b", type=float, help="active parameters (billions); = total for dense")
    ap.add_argument("--bandwidth-gbs", type=float, required=True,
                    help="memory bandwidth, GB/s: unified memory, or the GPU's VRAM with --vram-gib")
    ap.add_argument("--vram-gib", type=float,
                    help="discrete GPU: usable VRAM. Omit for unified memory")
    ap.add_argument("--ram-bandwidth-gbs", type=float,
                    help="discrete GPU: system RAM bandwidth for spilled weights")
    ap.add_argument("--ref-active-gb", type=float, help="measured reference: bytes read per token (GB)")
    ap.add_argument("--ref-tps", type=float, help="measured reference: decode tokens/s")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    out = {"name": a.name}
    weights = a.weights_gib
    if weights is None and a.params_b and a.bpw:
        weights = a.params_b * 1e9 * a.bpw / 8 / 2**30
        out["weights_note"] = "from params x bpw (estimate; prefer the real file size)"
    if weights is None:
        print("need --weights-gib, or --params-b with --bpw", file=sys.stderr)
        return 2
    kv_gib = None
    if a.kv_layers and a.kv_heads and a.kv_dim:
        per_tok = a.kv_layers * a.kv_heads * a.kv_dim * KV_BYTES[a.kv_type]
        kv_gib = per_tok * a.ctx / 2**30
        out["kv_kib_per_token"] = round(per_tok / 1024, 1)
    else:
        out["kv_note"] = "KV not computed (give --kv-layers --kv-heads --kv-dim)"
    foot = weights + (kv_gib or 0) + a.compute_gib
    resident = sum(a.resident)
    out.update(weights_gib=round(weights, 1), kv_gib=round(kv_gib, 1) if kv_gib is not None else None,
               compute_gib=a.compute_gib, footprint_gib=round(foot, 1), ctx=a.ctx,
               kv_type=a.kv_type, budget_gib=a.budget_gib)
    spill_frac = 0.0
    if a.vram_gib is None:          # unified memory: everything in one pool
        need_pool = foot
    else:                           # discrete: KV + compute in VRAM, then as many weights as fit
        room = a.vram_gib - (kv_gib or 0) - a.compute_gib
        out["vram_gib"] = a.vram_gib
        overflow = 0.0              # KV/compute that does not fit in VRAM either
        if room <= 0:
            out["vram_note"] = ("KV + compute alone exceed VRAM: everything spills; "
                                "lower ctx or use q8_0 KV")
            overflow, room = -room, 0.0
        spill = max(0.0, weights - room)
        spill_frac = spill / weights if weights else 0.0
        out.update(weights_in_vram_gib=round(weights - spill, 1), weights_in_ram_gib=round(spill, 1),
                   kv_compute_in_ram_gib=round(overflow, 1), fully_on_gpu=spill == 0 and room > 0)
        need_pool = spill + overflow  # what the system-RAM budget must hold
    out.update(fits_alone=need_pool <= a.budget_gib, headroom_alone_gib=round(a.budget_gib - need_pool, 1))
    if a.resident:
        out.update(resident_gib=round(resident, 1), fits_with_resident=need_pool + resident <= a.budget_gib,
                   headroom_with_resident_gib=round(a.budget_gib - need_pool - resident, 1))
    if a.active_b and a.bpw:
        gb = a.active_b * 1e9 * a.bpw / 8 / 1e9
        out["active_gb_per_token"] = round(gb, 2)
        if spill_frac and a.ram_bandwidth_gbs:
            out["bandwidth_ceiling_tps"] = round(
                1 / (gb * (1 - spill_frac) / a.bandwidth_gbs + gb * spill_frac / a.ram_bandwidth_gbs), 1)
        elif spill_frac:
            out["speed_note"] = "weights spill to RAM: give --ram-bandwidth-gbs for a speed estimate"
            out["bandwidth_ceiling_tps"] = None
        else:
            out["bandwidth_ceiling_tps"] = round(a.bandwidth_gbs / gb, 1)
        if a.ref_active_gb and a.ref_tps and not spill_frac:
            out["estimated_tps_from_reference"] = round(a.ref_tps * a.ref_active_gb / gb, 1)
        elif a.ref_active_gb and a.ref_tps:
            # the reference was measured fully on the GPU; scaling it says nothing about
            # the RAM-bound spilled part, so only the bandwidth ceiling is meaningful
            out["reference_note"] = "reference not applied: weights spill to RAM"
    elif a.active_b:
        out["speed_note"] = "give --bpw to estimate bytes per token"

    if a.json:
        print(json.dumps(out, indent=2))
        return 0
    print(f"{a.name}")
    print(f"  weights {out['weights_gib']} GiB" + (f"  ({out['weights_note']})" if "weights_note" in out else ""))
    if kv_gib is not None:
        print(f"  KV      {out['kv_gib']} GiB  ({out['kv_kib_per_token']} KiB/token x {a.ctx} ctx, {a.kv_type})")
    else:
        print(f"  KV      {out['kv_note']}")
    print(f"  compute {a.compute_gib} GiB")
    if a.vram_gib is None:
        print(f"  = footprint {out['footprint_gib']} GiB  vs budget {a.budget_gib} GiB: "
              f"{'FITS' if out['fits_alone'] else 'DOES NOT FIT'} alone ({out['headroom_alone_gib']:+} GiB)")
    else:
        print(f"  = footprint {out['footprint_gib']} GiB  vs {a.vram_gib} GiB VRAM: "
              + ("fully on the GPU" if out["fully_on_gpu"] else
                 f"{out['weights_in_ram_gib']} GiB of weights"
                 + (f" + {out['kv_compute_in_ram_gib']} GiB of KV/compute" if out["kv_compute_in_ram_gib"] else "")
                 + " spill to RAM "
                 f"({'fits' if out['fits_alone'] else 'DOES NOT FIT'} the {a.budget_gib} GiB RAM budget, "
                 f"{out['headroom_alone_gib']:+} GiB)"))
        if "vram_note" in out:
            print(f"  ! {out['vram_note']}")
    if a.resident:
        print(f"  with {out['resident_gib']} GiB resident: "
              f"{'FITS' if out['fits_with_resident'] else 'DOES NOT FIT'} ({out['headroom_with_resident_gib']:+} GiB)")
    if "active_gb_per_token" in out and out.get("bandwidth_ceiling_tps") is None:
        print(f"  reads ~{out['active_gb_per_token']} GB/token; {out['speed_note']}")
    elif "active_gb_per_token" in out:
        bw = (f"{a.bandwidth_gbs} GB/s VRAM + {a.ram_bandwidth_gbs} GB/s RAM" if spill_frac
              else f"{a.bandwidth_gbs} GB/s")
        print(f"  reads ~{out['active_gb_per_token']} GB/token; bandwidth ceiling "
              f"{out['bandwidth_ceiling_tps']} t/s at {bw} (an upper bound)")
        if "estimated_tps_from_reference" in out:
            print(f"  scaled from the measured reference: ~{out['estimated_tps_from_reference']} t/s (rough)")
    print("  note: estimates; the router's load log gives the real memory figure.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
