#!/usr/bin/env python3
"""Run NMF algorithms and calculate evaluation metrics"""
import argparse
from collections import Counter
from csv import DictReader, DictWriter
from itertools import product
import os
from pathlib import Path
from sys import stdin, stdout
from typing import Callable, List, TextIO, Tuple
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from sklearn.cluster import KMeans
from sklearn.decomposition import NMF
from sklearn.metrics import accuracy_score, normalized_mutual_info_score
from sklearn.model_selection import train_test_split


def load_data(root: str = 'data/CroppedYaleB',
              reduce: int = 4) -> Tuple[np.ndarray, np.ndarray]:
    """
    Load ORL (or Extended YaleB) dataset to numpy array.

    Args:
        root: path to dataset.
        reduce: scale factor for zooming out images.
    """
    images, labels = [], []

    for i, person in enumerate(sorted(os.listdir(root))):

        if not os.path.isdir(os.path.join(root, person)):
            continue

        for fname in os.listdir(os.path.join(root, person)):

            # Remove background images in Extended YaleB dataset.
            if fname.endswith('Ambient.pgm'):
                continue

            if not fname.endswith('.pgm'):
                continue

            # load image.
            img = Image.open(os.path.join(root, person, fname))
            img = img.convert('L')  # grey image.

            # reduce computation complexity.
            img = img.resize([s // reduce for s in img.size])

            # convert image to numpy array.
            img = np.asarray(img).reshape((-1, 1)) / SCALE

            # collect data and label.
            images.append(img)
            labels.append(i)

    # concate all images and labels.
    images = np.concatenate(images, axis=1)
    labels = np.array(labels)

    return images, labels


def assign_cluster_label(X: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Label the data according to clustering, for evaluation"""
    kmeans = KMeans(n_clusters=len(set(Y))).fit(X)
    Y_pred = np.zeros(Y.shape)

    for i in set(kmeans.labels_):
        ind = kmeans.labels_ == i
        Y_pred[ind] = Counter(Y[ind]).most_common(1)[0][0]  # assign label.

    return Y_pred


def plot(V: np.ndarray, img_size: Tuple[int, int]) -> None:
    """Face showing helper"""
    ind = 2  # index of demo image
    plt.imshow(SCALE * V[:, ind].reshape(img_size[1], img_size[0]),
               cmap=plt.cm.gray)
    plt.xticks(())
    plt.yticks(())


def nmf_baseline(K: int, X: np.ndarray,
                 steps: int) -> Tuple[np.ndarray, np.ndarray]:
    """Basic NMF algorithm, using sklearn library"""
    model = NMF(n_components=K, max_iter=steps)
    W = model.fit_transform(X)
    H = model.components_
    return W, H


def nmf(K: int,
        X: np.ndarray,
        steps: int,
        beta: float = 2,
        l1: float = 0,
        l2: float = 0,
        weight: Callable[[np.ndarray, np.ndarray, np.ndarray],
                         np.ndarray] = lambda x, w, h: 1,
        tol: float = 1e-3) -> Tuple[np.ndarray, np.ndarray]:
    """Generic NMF algorithm using multiplicative updates"""
    avg = np.sqrt(X.mean() / K)
    np.random.seed(0)
    W, H = avg * np.random.rand(len(X), K), avg * np.random.rand(K, len(X[0]))

    for _ in range(steps):
        W, H, done = mur(X, W, H, weight(X, W, H), beta, l1, l2, tol)
        if done:
            break

    return W, H


def mur(X: np.ndarray, W: np.ndarray, H: np.ndarray, U: np.ndarray,
        beta: float, l1: float, l2: float,
        tol: float) -> Tuple[np.ndarray, np.ndarray, bool]:
    """Weighted multiplicative update rule"""
    WH = W @ H
    d_W = U * X * WH**(beta - 2) @ H.T / (U * WH**(beta - 1) @ H.T + l1 +
                                          l2 * W)
    e_W = np.linalg.norm(W * (1 - d_W))
    W *= d_W
    WH = W @ H
    d_H = W.T @ (U * X * WH**(beta - 2)) / (W.T @ (U * WH**(beta - 1)) + l1 +
                                            l2 * H)
    H *= d_H
    e_H = np.linalg.norm(H * (1 - d_H))
    return W, H, e_W < tol and e_H < tol


def err(X: np.ndarray, W: np.ndarray, H: np.ndarray) -> np.ndarray:
    """Difference between the original and the reconstructed"""
    return X - W @ H


def tanh_weight(X: np.ndarray,
                W: np.ndarray,
                H: np.ndarray,
                p: float = 1) -> np.ndarray:
    """Weight calculation for tanhNMF"""
    E = err(X, W, H)
    a = X.size * p / (E**2).sum()
    return a * (1 - np.tanh(a * np.abs(E))**2)


def cim_weight(X: np.ndarray, W: np.ndarray, H: np.ndarray) -> np.ndarray:
    """Weight calculation for CIM NMF"""
    E2 = err(X, W, H)**2
    return np.exp(-E2 / E2.mean())


def l1_weight(X: np.ndarray, W: np.ndarray, H: np.ndarray) -> np.ndarray:
    """Weight calculation for l1 NMF"""
    return 1 / np.linalg.norm(err(X, W, H), ord=1)


def l21_weight(X: np.ndarray, W: np.ndarray, H: np.ndarray) -> np.ndarray:
    """Weight calculation for l21 NMF"""
    return 1 / np.linalg.norm(err(X, W, H), axis=0)


def tanh_nmf(K: int, X: np.ndarray,
             steps: int) -> Tuple[np.ndarray, np.ndarray]:
    """Another Robust NMF"""
    return nmf(K, X, steps, weight=tanh_weight)


def cim_nmf(K: int, X: np.ndarray,
            steps: int) -> Tuple[np.ndarray, np.ndarray]:
    """Robust NMF via half-quadratic minimization"""
    return nmf(K, X, steps, weight=cim_weight)


def l21_nmf(K: int, X: np.ndarray,
            steps: int) -> Tuple[np.ndarray, np.ndarray]:
    """Robust nonnegative matrix factorization using l21-norm"""
    return nmf(K, X, steps, weight=l21_weight)


def l1_nmf(K: int, X: np.ndarray, steps: int) -> Tuple[np.ndarray, np.ndarray]:
    """“Non-negative Matrix Factorization for Images with Laplacian Noise"""
    return nmf(K, X, steps, weight=l1_weight)


def kl_nmf(K: int, X: np.ndarray, steps: int) -> Tuple[np.ndarray, np.ndarray]:
    """Algorithms for nonnegative matrix factorization with the β-divergence"""
    return nmf(K, X, steps, beta=1)


def no_noise(shape: Tuple[int, int], scale: float) -> float:
    """No noise"""
    return 0


def salt_and_pepper(shape: Tuple[int, int],
                    p: float = 0.4,
                    r: float = 0.3) -> np.ndarray:
    """Randomly change some pixels to black or white"""
    p_noise = np.random.rand(*shape) <= p
    r_noise = np.random.rand(*shape) <= r
    return 1 * (p_noise * r_noise) - 1 * (p_noise * ~r_noise)


def uniform(shape: Tuple[int, int], scale: float = 0.1) -> np.ndarray:
    """Uniform noise"""
    return scale * (np.random.rand(*shape) - 0.5)


def laplace(shape: Tuple[int, int], scale: float = 0.1) -> np.ndarray:
    """Laplace noise"""
    return np.random.laplace(scale=scale)


def gaussian(shape: Tuple[int, int], scale: float = 0.1) -> np.ndarray:
    """Gaussian noise"""
    return np.random.normal(scale=scale)


def evaluate_algorithm(
        V: np.ndarray, V_hat: np.ndarray, Y_hat: np.ndarray, algorithm: str,
        steps: int) -> Tuple[float, float, float, np.ndarray, np.ndarray]:
    """Fit model and run evaluation metrics"""
    W, H = ALGORITHMS[algorithm](len(set(Y_hat)), V, steps)

    # Assign cluster labels.
    Y_pred = assign_cluster_label(H.T, Y_hat)

    rre = np.linalg.norm(V_hat - W @ H) / np.linalg.norm(V_hat)
    acc = accuracy_score(Y_hat, Y_pred)
    nmi = normalized_mutual_info_score(Y_hat, Y_pred)
    return rre, acc, nmi, W, H


def graph(summary: TextIO, figures: str) -> None:
    """Read summary results and output graphs"""
    data = {}

    for r in DictReader(summary):
        k = (r['dataset'], r['noise'])

        if k in data:
            if r['algorithm'] in data[k]:
                data[k][r['algorithm']].append(r)
            else:
                data[k][r['algorithm']] = [r]
        else:
            data[k] = {r['algorithm']: [r]}

    for (dataset, noise), d in data.items():
        figure()

        for i, measure in enumerate(MEASURES, 1):
            plt.subplot(1, len(MEASURES), i)

            for algorithm, rows in d.items():
                plt.errorbar([float(r['noiselevel']) for r in rows],
                             [float(r[measure]) for r in rows],
                             [float(r[f'{measure}_std']) for r in rows])

            plt.xlabel('noise level')
            plt.title(measure)

        plt.legend(d.keys())
        plt.tight_layout()
        plt.savefig(f'{figures}/{dataset}_{noise}.png')


def figure() -> None:
    """Helper to create new figure"""
    plt.figure(figsize=(10, 3))


def run_nmf_algorithms(summary: TextIO, results: TextIO, algorithms: List[str],
                       noises: List[str], trials: int, figures: str, data: str,
                       datasets: List[str], steps: int) -> None:
    """Run all combinations of algorithms and data and record results"""
    header = ['dataset', 'noise', 'noiselevel', 'algorithm'] + MEASURES
    w_summary = DictWriter(summary, header + [f'{x}_std' for x in MEASURES])
    w_summary.writeheader()
    w = DictWriter(results, header + ['trial'])
    w.writeheader()
    Y_hats = [None] * trials
    V_hats, Vs = Y_hats.copy(), Y_hats.copy()
    rre = np.zeros(len(Y_hats))
    acc, nmi = rre.copy(), rre.copy()

    for dataset in datasets:
        np.random.seed(0)
        red, imgsize = DATASETS[dataset]

        # Load dataset.
        V_hat_orig, Y_hat_orig = load_data(f'{data}/{dataset}', red)
        img_size = [i // red for i in imgsize]

        for i in range(len(Y_hats)):
            V_hats[i], _, Y_hats[i], _ = train_test_split(V_hat_orig.T,
                                                          Y_hat_orig,
                                                          train_size=0.9)
            V_hats[i] = V_hats[i].T

        for noise, noise_fn, k, p in ((noise, NOISES[noise][0], k, p)
                                      for noise in noises
                                      for k, p in enumerate(NOISES[noise][1])):
            row = {
                'dataset': dataset,
                'noise': noise.replace('_', '-'),
                'noiselevel': p,
            }

            # Add Noise
            np.random.seed(0)
            Vs = [np.clip(v + noise_fn(v.shape, p), 1e-7, 1) for v in V_hats]

            if figures:
                figure()

                for i, v in enumerate(Vs):
                    plt.subplot(trials,
                                len(algorithms) + 1,
                                (len(algorithms) + 1) * i + 1)
                    plot(v, img_size)

                    if i == 0:
                        plt.title('input')

            for a, algorithm in enumerate(algorithms, 1):
                row['algorithm'] = algorithm.replace('_', '-')

                for i, (V, V_hat, Y_hat) in enumerate(zip(Vs, V_hats, Y_hats)):
                    rre[i], acc[i], nmi[i], W, H = evaluate_algorithm(
                        V, V_hat, Y_hat, algorithm, steps)

                    if figures:
                        plt.subplot(trials,
                                    len(algorithms) + 1,
                                    (len(algorithms) + 1) * i + a + 1)
                        plot(W @ H, img_size)

                        if i == 0:
                            plt.title(row['algorithm'])

                    w.writerow({
                        **row,
                        'trial': i + 1,
                        'RRE': rre[i],
                        'Acc': acc[i],
                        'NMI': nmi[i],
                    })

                w_summary.writerow({
                    **row,
                    'RRE': '{:.4f}'.format(rre.mean()),
                    'RRE_std': '{:.4f}'.format(rre.std()),
                    'Acc': '{:.4f}'.format(acc.mean()),
                    'Acc_std': '{:.4f}'.format(acc.std()),
                    'NMI': '{:.4f}'.format(nmi.mean()),
                    'NMI_std': '{:.4f}'.format(nmi.std()),
                })

            if figures:
                plt.subplots_adjust(wspace=0, hspace=0)
                plt.savefig(f'{figures}/{dataset}_{noise}_{k}.png',
                            bbox_inches='tight',
                            pad_inches=0)


def main() -> None:
    """Run all algorithms"""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-r',
                        '--results',
                        default='results.csv',
                        help='outcome of each trial')
    parser.add_argument('-p',
                        '--figures',
                        default='figures',
                        help='output image directory')
    parser.add_argument('-k',
                        '--trials',
                        type=int,
                        default=5,
                        help='number of trials per combination')
    parser.add_argument('-m',
                        '--steps',
                        type=int,
                        default=100,
                        help='number of multiplicative updates')
    parser.add_argument('-f',
                        '--summary',
                        help='summary file, or stdio if not specified')
    parser.add_argument('-d',
                        '--no-figures',
                        dest='figures',
                        action='store_false',
                        help='disable image output')
    parser.add_argument('-s',
                        '--no-results',
                        dest='results',
                        action='store_false',
                        help='disable results output')
    parser.add_argument('-q',
                        '--quiet',
                        action='store_true',
                        help='disable summary output')
    parser.add_argument(
        '-n',
        '--noises',
        default='no_noise,salt_and_pepper,uniform,laplace,gaussian',
        help='which noise types to try')
    parser.add_argument('-i',
                        '--data',
                        default='data',
                        help='input data directory')
    parser.add_argument('-t',
                        '--datasets',
                        default='ORL,CroppedYaleB',
                        help='which datasets to try')
    parser.add_argument('-g',
                        '--graph',
                        action='store_true',
                        help='generate graphs from results')
    parser.add_argument('algorithms',
                        nargs='*',
                        default=[
                            'nmf_baseline', 'nmf', 'kl_nmf', 'l1_nmf',
                            'l21_nmf', 'cim_nmf', 'tanh_nmf'
                        ],
                        help='which algorithms to try')
    args = parser.parse_args()

    if args.figures:
        Path(args.figures).mkdir(parents=True, exist_ok=True)

    if args.graph:
        with open(args.summary if args.summary else os.devnull) as f:
            graph(f if args.summary else stdin, args.figures)
        return

    with open(args.summary if args.summary and not args.quiet else os.devnull,
              'w') as o, open(args.results or os.devnull, 'w') as r:
        run_nmf_algorithms(o if args.summary or args.quiet else stdout, r,
                           args.algorithms, args.noises.split(','),
                           args.trials, args.figures, args.data,
                           args.datasets.split(','), args.steps)


SCALE = 255
ALGORITHMS = {
    'nmf_baseline': nmf_baseline,
    'nmf': nmf,
    'kl_nmf': kl_nmf,
    'l1_nmf': l1_nmf,
    'l21_nmf': l21_nmf,
    'cim_nmf': cim_nmf,
    'tanh_nmf': tanh_nmf
}
DATASETS = {'ORL': (3, (92, 112)), 'CroppedYaleB': (4, (168, 192))}
NOISES = {
    'no_noise': (no_noise, [0]),
    'salt_and_pepper': (salt_and_pepper, [0.1, 0.2, 0.3, 0.4]),
    'uniform': (uniform, [0.1, 0.2, 0.3, 0.4]),
    'laplace': (laplace, [0.1, 0.2, 0.3, 0.4]),
    'gaussian': (gaussian, [0.1, 0.2, 0.3, 0.4])
}
MEASURES = ['RRE', 'Acc', 'NMI']

if __name__ == '__main__':
    main()
