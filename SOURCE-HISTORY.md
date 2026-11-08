# Source snapshots and GitHub history

Upstream: [https://github.com/Canner/WrenAI](https://github.com/Canner/WrenAI) at `548eee3e864b11e7f11eee15ae82be178a295f22`.

The local maintenance history starts from a downloaded upstream source archive. This repository imports those reviewed snapshots after the owner's initial repository commit. GitHub commits are recreated through the connected API, so their commit IDs differ; **all nine imported Git trees were checked to match the local trees exactly**.

| Local source commit | GitHub commit | Matching tree | Change |
|---|---|---|---|
| `6d5e83210dd1` | [`dda64ed280dd`](https://github.com/hjt2007323/Wren/commit/dda64ed280dd57d33d6accee851c1f1aac5e3d78) | `96520e51b9b7` | chore: vendor WrenAI 548eee3e (sdk/** Apache-2.0) as upstream baseline |
| `dfd90dedfe14` | [`32c50cb846bc`](https://github.com/hjt2007323/Wren/commit/32c50cb846bc93d73d1e42bbbad0d82c26f4c688) | `e369c2ac02ec` | feat(sdk): unify 16 KiB UTF-8 content budget across wren-langchain formatters |
| `1a3480bdaa04` | [`cec4f7823ec4`](https://github.com/hjt2007323/Wren/commit/cec4f7823ec4a0c4a31479f1d52a79ac77179e33) | `934831cee9b6` | docs(g2): frozen case table, delivery receipt, evidence and interview notes |
| `4e9f52350310` | [`469e5077eb90`](https://github.com/hjt2007323/Wren/commit/469e5077eb903f9f842ccdbd08db2f6f7b5ba0fc) | `5a28641eecee` | chore(g2): refresh evidence snapshot and align reported numbers |
| `86b78d42742a` | [`1ff77e4ac608`](https://github.com/hjt2007323/Wren/commit/1ff77e4ac60877d4e2b9b5cecd83e30e629b40f6) | `ed11f84f2173` | docs(g2): add path/size/hash manifest for delivery artifacts |
| `780e1d90f9b0` | [`7d259331dfbf`](https://github.com/hjt2007323/Wren/commit/7d259331dfbf8ac0757476e70b8a353f6eec838f) | `d1a1ac222f94` | test(g2): add tool-level budget tests, red-run plugin and acceptance matrix |
| `1b0a34925221` | [`6da0610bf285`](https://github.com/hjt2007323/Wren/commit/6da0610bf285901e4e3475cbeac5d53166ed323a) | `f6f4c5f5ea9e` | docs(g2): record independent acceptance R1 and re-pin manifests |
| `ab4df18057a5` | [`2943b5784ec8`](https://github.com/hjt2007323/Wren/commit/2943b5784ec8ba6559b15812b9fd8c2ed1683dd9) | `c209b0c52503` | docs(g2): add monitoring-probe cross-check for the accepted build |
| `35f6e3e196f2` | [`8e37a41b4b2e`](https://github.com/hjt2007323/Wren/commit/8e37a41b4b2e4a018d1bc71b0f5deef60d7f0b67) | `beb5208724cb` | docs: prepare attributed component portfolio publication |

The owner's initial README and license scaffold remain in the first commit. Current files retain the upstream license texts and applicable path mapping. Component behavior, tests and evidence are described on the main README; the upstream framework is attributed in UPSTREAM.md.

Machine-readable mapping: [SOURCE-HISTORY.json](SOURCE-HISTORY.json).
