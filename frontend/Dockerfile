FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# Next inlines NEXT_PUBLIC_* into the bundle at build time, so this has to be a build arg.
# It is the browser that calls the API, so the value must be the host and port the browser
# sees - not the compose service name, which only resolves inside the network.
ARG NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

# Same rule for the demo reset: inlined at build time, so both have to be build args.
ARG NEXT_PUBLIC_DEMO_RESET_ENABLED=false
ENV NEXT_PUBLIC_DEMO_RESET_ENABLED=$NEXT_PUBLIC_DEMO_RESET_ENABLED
ARG NEXT_PUBLIC_DEMO_RESET_TOKEN=
ENV NEXT_PUBLIC_DEMO_RESET_TOKEN=$NEXT_PUBLIC_DEMO_RESET_TOKEN

COPY . .
RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "start"]
