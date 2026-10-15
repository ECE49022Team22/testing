# YOLO accuracy: PyTorch vs NCNN exports (640 / 416 / 320 px)

Copied from `stop-sign-eval/results_ncnn/`, produced on the Pi 5 (2026-10-08) with:

    cd ~/stop-sign-eval
    python get_data.py && python make_synthetic.py
    OMP_WAIT_POLICY=passive taskset -c 2,3 python evaluate.py --results results_ncnn \
        --weights yolo26n_640_ncnn_model="NCNN 640" --weights yolo26n_416_ncnn_model="NCNN 416" \
        --weights yolo26n_320_ncnn_model="NCNN 320"

The NCNN models were made with `yolo export model=yolo26n.pt format=ncnn imgsz=<640|416|320>`.
`summary.md` has every table; the time-per-frame column is from that run (default NCNN threads).
