import torch
from diffusers import FluxPipeline

print('Loading FLUX.1-schnell...')
pipe = FluxPipeline.from_pretrained(
    'black-forest-labs/FLUX.1-schnell',
    torch_dtype=torch.float16,
)
pipe.enable_sequential_cpu_offload()

print('Generating test image...')
image = pipe(
    'Semi-realistic dark portrait of a Korean woman, investigative journalist, short bob-cut hair, sharp watchful eyes, dark industrial horror aesthetic, muted purple-grey palette',
    height=512,
    width=512,
    num_inference_steps=4,
    guidance_scale=0.0,
).images[0]

image.save('storage/renders/flux-test.png')
print('DONE - saved to storage/renders/flux-test.png')
