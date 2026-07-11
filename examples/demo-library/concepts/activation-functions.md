---
title: Activation Functions
created: '2026-04-29'
updated: '2026-04-29'
confidence: 0.85
last_reinforced: '2026-04-29'
tier: semantic
quality: 0.85
scope: private
author: hermes-quant
---

- conforms_to::[[concept-form-contract]]
- has_status::[[growing]]
- in_domain::[[machine-learning]]

# Activation Functions

> In most cases you can use the ReLU activation function in the hidden layers (or one of its variants, as we will see in Chapter 11). It is a bit faster to compute than other activation functions, and Gradient Descent does not get stuck as much on plateaus, thanks to the fact that it does not saturate for large input values (as opposed to the logistic function or the hyperbolic tangent function, which saturate at 1).
> — Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0140

> For the output layer, the softmax activation function is generally a good choice for classification tasks (when the classes are mutually exclusive). For regression tasks, you can simply use no activation function at all.
> — Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0141

![[raw/papers/hands-on-ml-scikit-learn-tensorflow/chapters/ch-10-introduction-to-artificial-neural-networks#^hands-on-ml-scikit-learn-tensorflow-ch10-0140]]

![[raw/papers/hands-on-ml-scikit-learn-tensorflow/chapters/ch-10-introduction-to-artificial-neural-networks#^hands-on-ml-scikit-learn-tensorflow-ch10-0141]]

Activation functions are the non-linear transformations applied to the weighted sum of inputs at each neuron in an artificial neural network. They are the mechanism that gives neural networks their expressive power — without them, stacking layers would collapse into a single linear transformation, no matter how deep the network. Chapter 10 of *Hands-On Machine Learning with Scikit-Learn and TensorFlow* covers four activation functions essential to the history and practice of neural networks: the Heaviside step function (used in Perceptrons), the logistic/sigmoid function (which enabled backpropagation), the hyperbolic tangent (tanh), and the Rectified Linear Unit (ReLU), along with the softmax function for multi-class output layers. The choice of activation function determines whether gradient-based learning is possible at all, how quickly the network converges, and whether training stalls due to vanishing or exploding gradients.

## Author's Words

> "The most common step function used in Perceptrons is the Heaviside step function (see Equation 10-1). Sometimes the sign function is used instead."
> — Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0028

> "[The authors] replaced the step function with the **logistic function**, σ(z) = 1 / (1 + exp(–z)). This was essential because the step function contains only flat segments, so there is no gradient to work with (Gradient Descent cannot move on a flat surface), while the logistic function has a well-defined nonzero derivative everywhere, allowing Gradient Descent to make some progress at every step."
> — Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0061

> "The **hyperbolic tangent function** tanh(z) = 2σ(2z) – 1. Just like the logistic function it is S-shaped, continuous, and differentiable, but its output value ranges from –1 to 1 (instead of 0 to 1 in the case of the logistic function), which tends to make each layer's output more or less normalized (i.e., centered around 0) at the beginning of training. This often helps speed up convergence."
> — Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0062

> "**ReLU**(z) = max(0, z). It is continuous but unfortunately not differentiable at z = 0 (the slope changes abruptly, which can make Gradient Descent bounce around). However, in practice it works very well and has the advantage of being fast to compute. Most importantly, the fact that it does not have a maximum output value also helps reduce some issues during Gradient Descent."
> — Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0063

> "In most cases you can use the ReLU activation function in the hidden layers (or one of its variants, as we will see in Chapter 11). It is a bit faster to compute than other activation functions, and Gradient Descent does not get stuck as much on plateaus, thanks to the fact that it does not saturate for large input values (as opposed to the logistic function or the hyperbolic tangent function, which saturate at 1)."
> — Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0140

> "Biological neurons seem to implement a roughly sigmoid (S-shaped) activation function, so researchers stuck to sigmoid functions for a very long time."
> — Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0070

> "For the output layer, the softmax activation function is generally a good choice for classification tasks (when the classes are mutually exclusive). For regression tasks, you can simply use no activation function at all."
> — Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0141

## Author's Formulation

The author presents activation functions as the critical architectural choice that determines both the **trainability** and the **performance** of a neural network. The chapter documents four key activation functions:

### Heaviside Step Function (Equation 10-1)

$$
\text{heaviside}(z) =
\begin{cases}
0 & \text{if } z < 0 \\
1 & \text{if } z \geq 0
\end{cases}
$$

Alternatively, the sign function:
$$
\text{sgn}(z) =
\begin{cases}
-1 & \text{if } z < 0 \\
0 & \text{if } z = 0 \\
+1 & \text{if } z > 0
\end{cases}
$$

*Context (lines 69–73):* Used in the classic Perceptron. Step functions are binary — they output 0 or 1 (or –1, 0, +1 for the sign function). The derivative is zero almost everywhere, making gradient-based learning impossible. This is the *only* activation function in the chapter that is incompatible with [[backpropagation]].

### Logistic (Sigmoid) Function

$$
\sigma(z) = \frac{1}{1 + \exp(-z)}
$$

*Context (line 146):* S-shaped, continuous, and differentiable. Output range: $(0, 1)$. This activation function was the **key architectural change** that enabled backpropagation — replacing the step function with σ(z) gave the network a well-defined nonzero derivative everywhere, allowing [[gradient-descent]] to make progress at every step. However, σ(z) saturates at its extremes (output approaches 0 or 1), where the gradient approaches zero, causing the vanishing gradient problem in deep networks.

### Hyperbolic Tangent (tanh)

$$
\tanh(z) = 2\sigma(2z) - 1
$$

*Context (lines 148–150):* S-shaped, continuous, differentiable. Output range: $(-1, 1)$. The key benefit over the logistic function is that tanh is centered around 0 (zero-centered), which tends to normalize each layer's output at the beginning of training and often speeds up convergence. Like logistic, tanh also saturates at its extremes ($-1$ and $1$), producing near-zero gradients.

### ReLU (Rectified Linear Unit)

$$
\text{ReLU}(z) = \max(0, z)
$$

*Context (lines 152–154):* Continuous but not differentiable at $z = 0$ in the strict mathematical sense. Output range: $[0, \infty)$. ReLU is the **default recommendation** for hidden layers in Chapter 10. Its three advantages: (1) fast to compute (simple max operation), (2) no upper bound prevents saturation for large positive inputs, (3) empirically works better than sigmoids in most contexts. The trade-off is that ReLU can "die" — neurons that enter the zero region output 0 for all inputs and stop learning (the "dying ReLU" problem).

### Softmax (Output Layer)

For multi-class classification with $K$ mutually exclusive classes, the softmax function converts logits into a probability distribution:

$$
\hat{p}_k = \frac{\exp(z_k)}{\sum_{j=1}^{K} \exp(z_j)}
$$

*Context (lines 161–164):* Softmax is not applied per-neuron like the other activation functions; it is a shared transformation across all output neurons. Each output $\hat{p}_k$ represents the estimated probability that the input belongs to class $k$. The predicted class is $\arg\max_k \hat{p}_k$.

## Specific Examples

### Example 1: Step Function vs. Logistic Function — The Gradient Problem

The following table contrasts the two functions that bookend the history of neural network training:

| Property | Heaviside Step | Logistic (Sigmoid) |
|----------|---------------|-------------------|
| Derivative at $z \neq 0$ | $0$ | $\sigma(z)(1 - \sigma(z)) \neq 0$ |
| Derivative at $z = 0$ | undefined (discontinuity) | $\sigma(0)(1 - \sigma(0)) = 0.25$ |
| Gradient available for GD? | **No** — "no gradient to work with" | **Yes** — "well-defined nonzero derivative everywhere" |
| Used in | Perceptrons (pre-1986) | MLPs with backpropagation (post-1986) |

The step function's flat segments mean Gradient Descent "cannot move on a flat surface" — any weight that produces a $z < 0$ or $z \geq 0$ yields the same output, providing no directional information for updates. The logistic function's smooth, nonzero gradient everywhere was the breakthrough that made MLP training possible.

### Example 2: ReLU vs. Sigmoid on a Deep MNIST Network

The book demonstrates a DNN on MNIST with two hidden layers (300 and 100 neurons). With ReLU activation in the hidden layers and softmax output, the model reaches **98.18% test accuracy** after 40,000 steps using TF.Learn's `DNNClassifier`. The author notes ReLU is the default for these hidden layers: "Under the hood, the DNNClassifier class creates all the neuron layers, based on the ReLU activation function."

### Example 3: Tanh Zero-Centering vs. Logistic Output Range

| Function | Output Range | Zero-Centered? | Convergence Property |
|----------|-------------|----------------|---------------------|
| Logistic | $(0, 1)$ | No (all outputs positive) | Slower — layer outputs are not normalized |
| Tanh | $(-1, 1)$ | Yes (centered around 0) | Faster — "tends to make each layer's output more or less normalized" |

The logistic function always outputs positive values, which can cause the gradients of weights flowing into a neuron to be all positive or all negative — creating a zigzagging optimization path. Tanh's zero-centered output mitigates this issue.

### Example 4: Perceptron with Heaviside Step on Iris

```python
import numpy as np
from sklearn.datasets import load_iris
from sklearn.linear_model import Perceptron

iris = load_iris()
X = iris.data[:, (2, 3)]  # petal length, petal width
y = (iris.target == 0).astype(np.int)  # Iris Setosa?

per_clf = Perceptron(random_state=42)
per_clf.fit(X, y)
y_pred = per_clf.predict([[2, 0.5]])
```

The Perceptron uses a Heaviside step function internally — the output is a hard binary decision (0 or 1), not a probability. The author notes: "contrary to Logistic Regression classifiers, Perceptrons do not output a class probability; rather, they just make predictions based on a hard threshold."

## Implementation Details

### Activation Function in TensorFlow `neuron_layer()` Function

The book's custom layer builder applies activation as a post-processing step on the linear transformation $\mathbf{Z} = \mathbf{X} \cdot \mathbf{W} + \mathbf{b}$:

```python
def neuron_layer(X, n_neurons, name, activation=None):
    with tf.name_scope(name):
        n_inputs = int(X.get_shape()[1])
        stddev = 2 / np.sqrt(n_inputs)
        init = tf.truncated_normal((n_inputs, n_neurons), stddev=stddev)
        W = tf.Variable(init, name="weights")
        b = tf.Variable(tf.zeros([n_neurons]), name="biases")
        z = tf.matmul(X, W) + b
        if activation == "relu":
            return tf.nn.relu(z)
        else:
            return z  # linear output (logits)
```

Key design decisions:
- **No activation argument for sigmoid or tanh** — Chapter 10 only implements ReLU vs. linear in the custom function
- **Logits preservation** — the output layer is deliberately left linear (`activation=None`) so that softmax cross-entropy can be applied in a numerically stable combined operation: `tf.nn.sparse_softmax_cross_entropy_with_logits()`
- The author notes this combined operation "is equivalent to applying the softmax activation function and then computing the cross entropy, but it is more efficient"

### Using `fully_connected()` (TensorFlow contrib)

The built-in alternative applies activation via the `activation_fn` parameter:

```python
from tensorflow.contrib.layers import fully_connected

with tf.name_scope("dnn"):
    hidden1 = fully_connected(X, n_hidden1, scope="hidden1")         # default: ReLU
    hidden2 = fully_connected(hidden1, n_hidden2, scope="hidden2")  # default: ReLU
    logits = fully_connected(hidden2, n_outputs, scope="outputs",
                             activation_fn=None)                     # linear for output
```

### DNNClassifier Default Activation

Under the hood, `tf.contrib.learn.DNNClassifier` uses ReLU activation for all hidden layers. The author notes: "we can change this by setting the activation_fn hyperparameter."

### Softmax for Inference on New Data

When using a trained model for prediction, raw logits are sufficient for class selection:

```python
Z = logits.eval(feed_dict={X: X_new_scaled})
y_pred = np.argmax(Z, axis=1)  # class with highest logit
```

"If you wanted to know all the estimated class probabilities, you would need to apply the softmax() function to the logits, but if you just want to predict a class, you can simply pick the class that has the highest logit value."

## Figures and Diagrams

### Figure 10-8 — Activation Functions and Their Derivatives

The chapter includes a multi-panel plot (Figure 10-8, line 156) showing three activation functions and their derivatives side by side:

1. **Logistic (Sigmoid)** — Left panel: σ(z) plotted as an S-shaped curve from (0,0) to asymptotes at 0 and 1. Its derivative σ′(z) = σ(z)(1 − σ(z)) is a bell-shaped curve peaking at 0.25 at z=0.
2. **Hyperbolic Tangent (tanh)** — Center panel: tanh(z) plotted as an S-shaped curve passing through (0,0) with asymptotes at −1 and +1. Its derivative is a narrower, taller bell curve peaking at 1.0 at z=0.
3. **ReLU** — Right panel: ReLU(z) = max(0,z) shown as zero for z < 0 and the identity line for z ≥ 0. Its derivative (subgradient) shown as 0 for z < 0 and 1 for z > 0, with a discontinuity at z=0.

The key visual message: logistic and tanh have near-zero derivatives at their extremes (saturation), while ReLU maintains a constant derivative of 1 for all positive inputs — explaining why ReLU avoids the vanishing gradient problem.

### Figure 10-9 — Modern MLP with ReLU and Softmax

Figure 10-9 (line 164) depicts the architecture of a modern feedforward neural network for classification: an input layer feeds into hidden layers using ReLU activation (depicted as rectifier symbols), and the output layer uses a shared softmax function that converts logits into a probability distribution summing to 1. Signal flow is strictly one-directional (feedforward). Each output neuron corresponds to a class label, and the network outputs estimated probabilities $\hat{p}_0$ through $\hat{p}_9$ for 10-class digit classification.

## Author's Warnings

### ⚠ Warning 1: Step Function Has Zero Gradient — Incompatible with Backpropagation
> **Sensitivity:** 🔴 **Critical**
>
> "The step function contains only flat segments, so there is no gradient to work with (Gradient Descent cannot move on a flat surface), while the logistic function has a well-defined nonzero derivative everywhere."
>
> This is the fundamental reason Perceptrons with step functions cannot be trained with backpropagation. Any neural network using a non-differentiable activation (like Heaviside or sign) is incompatible with gradient-based learning unless the activation is replaced with a smooth approximation.

### ⚠ Warning 2: Logistic and Tanh Saturate — Vanishing Gradients
> **Sensitivity:** 🟠 **High**
>
> "Gradient Descent does not get stuck as much on plateaus, thanks to the fact that [ReLU] does not saturate for large input values (as opposed to the logistic function or the hyperbolic tangent function, which saturate at 1)."
>
> Both logistic and tanh produce gradients that approach zero as the input moves toward positive or negative extremes. In deep networks, this means early layers receive vanishingly small weight updates — the vanishing gradient problem. This is why ReLU is the preferred default for hidden layers.

### ⚠ Warning 3: ReLU Is Not Differentiable at z = 0 — Gradient Descent Instability
> **Sensitivity:** 🟡 **Medium**
>
> "It is continuous but unfortunately not differentiable at z = 0 (the slope changes abruptly, which can make Gradient Descent bounce around)."
>
> The sharp corner at $z = 0$ means the subgradient is not uniquely defined. In practice this is rarely a problem, but the author references Chapter 11 for smoother variants like ELU and leaky ReLU that address this issue.

### ⚠ Warning 4: ReLU Can "Die" — Permanently Inactive Neurons
> **Sensitivity:** 🟠 **High**
>
> Implicit in the chapter (explicitly addressed in Chapter 11): ReLU neurons that enter the zero-output region for all training instances become permanently inactive — they output 0 for every input and their weights stop updating because the gradient through a ReLU at $z < 0$ is zero. This is the "dying ReLU" phenomenon. The chapter recommends ReLU variants (leaky ReLU, ELU, etc.) as mitigations.

### ⚠ Warning 5: Softmax Requires Mutually Exclusive Classes
> **Sensitivity:** 🟡 **Medium**
>
> "For the output layer, the softmax activation function is generally a good choice for classification tasks (when the classes are mutually exclusive)."
>
> Softmax forces the output probabilities to sum to 1, making it inappropriate for multi-label classification where multiple classes can be present simultaneously. For multi-label tasks, the author recommends using independent sigmoid units per output neuron instead.

## Limitations and Counter-Arguments

1. **Only four activation functions covered** — Chapter 10 covers only Heaviside step, logistic, tanh, and ReLU (plus softmax for outputs). Modern deep learning uses dozens of activation functions including leaky ReLU, ELU, SELU, GELU, Swish, Mish, and parametric variants. The author acknowledges this by pointing to Chapter 11 for "variants" of ReLU.

2. **ReLU is not always optimal** — While the author recommends ReLU as the default for hidden layers ("in most cases you can use the ReLU activation function"), ReLU is known to be suboptimal for certain architectures (e.g., very deep networks without skip connections, or networks using batch normalization). ELU and SELU often outperform ReLU in deeper architectures.

3. **No discussion of activation function impact on initialization** — The choice of activation function is tightly coupled to weight initialization strategy. The author uses $\sqrt{2 / n_{\text{inputs}}}$ as the standard deviation for truncated normal initialization, which is appropriate for ReLU (He initialization) but would be suboptimal for sigmoid or tanh (which require Glorot/Xavier initialization). This dependency is only hinted at with "using this specific standard deviation helps the algorithm converge much faster."

4. **Biological plausibility is mentioned but not deeply explored** — The author notes "Biological neurons seem to implement a roughly sigmoid (S-shaped) activation function" but modern neuroscience suggests biological neurons are far more complex than any single mathematical function used in ANNs. The biological analogy serves as motivational framing rather than a rigorous design constraint.

5. **Step function limitations drove the first AI winter** — Minsky and Papert's 1969 critique of Perceptrons (which used step functions) was devastating precisely because the step function's flat gradient made gradient-based training impossible at the time. The shift to logistic activation was not just an improvement — it was a **necessary condition** for the entire deep learning revolution that followed.

## Historical / Empirical Context

The Heaviside step function, named after the English electrical engineer Oliver Heaviside (1850–1925), was adopted by McCulloch and Pitts in their 1943 logical model of the neuron. Frank Rosenblatt's 1957 Perceptron used this step function (or the sign function) as its activation, meaning Perceptron outputs were hard binary decisions. The decision to use a non-differentiable activation was not a design oversight — it reflected the binary, logic-gate view of neural computation that dominated early ANN research.

The logistic (sigmoid) function had been used in statistics (logistic regression) since the 1950s, but its application to neural networks was the critical insight in Rumelhart, Hinton, and Williams's 1986 backpropagation paper. The shift from step to sigmoid was described as a "key change to the MLP's architecture" because it made gradient-based learning possible.

ReLU was known in biological neuroscience (the rectification property of biological neurons was observed by Sherrington in the early 20th century) but was not widely adopted in ANNs until the late 2000s and early 2010s. Its practical superiority over sigmoid/tanh was demonstrated empirically by Nair and Hinton (2010) and Krizhevsky et al. (2012) on ImageNet. ReLU's combination of fast computation, non-saturating behavior, and sparse activation made it the default for modern deep learning.

The MNIST experiment in Chapter 10 achieved **98.18% test accuracy** using ReLU hidden layers and softmax output — a result that would have been impossible with step-function Perceptrons (which cannot solve XOR, let alone 10-class digit classification) and would have been much harder or impossible with sigmoid activations in deeper networks due to vanishing gradients.

## Relations

- extracted_from::[[hands-on-ml-scikit-learn-tensorflow]]
  - Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0028 — Heaviside step and sign function definitions (Equation 10-1)
  - Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0061 — logistic function as the key replacement for step function enabling backpropagation
  - Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0062 — hyperbolic tangent (tanh) function, zero-centered property
  - Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0063 — ReLU function, non-differentiability at zero
  - Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0064 — Figure 10-8 activation functions and their derivatives
  - Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0067..0069 — softmax for mutually exclusive classification, Figure 10-9 modern MLP
  - Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0070 — biological neurons implement sigmoid activation
  - Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0092..0096 — `neuron_layer()` function implementation with ReLU
  - Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0140 — ReLU as default recommendation for hidden layers
  - Ch. 10, block ^hands-on-ml-scikit-learn-tensorflow-ch10-0141 — softmax for classification output, no activation for regression

- informed_by::[[backpropagation]]
  - Backpropagation requires differentiable activation functions; the step function's zero gradient made it incompatible, forcing the shift to logistic/sigmoid activations.

- informed_by::[[gradient-descent]]
  - The saturating behavior of logistic and tanh functions causes vanishing gradients in deep networks, a primary motivation for adopting ReLU activation in hidden layers.

- relates_to::[[batch-normalization]]
  - Chapter 11 introduces Batch Normalization as a complementary technique that can reduce the impact of activation function choice on training stability.

- relates_to::[[dropout]]
  - The choice of activation function interacts with regularization; ReLU's sparse activations complement dropout's neuron-dropping mechanism.

- relates_to::[[feature-engineering]]
  - Activation functions apply non-linear transformations at the neuron level, analogous to how feature engineering applies transformations at the data level — both introduce non-linearity and increase representational capacity.