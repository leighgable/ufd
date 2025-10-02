{
  description = "AI on Nix with uv";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    llama-cpp.url = "github:ggml-org/llama.cpp";
  };

  outputs =
    { nixpkgs, llama-cpp, ... }:
    let
      inherit (nixpkgs) lib;
      forAllSystems = lib.genAttrs lib.systems.flakeExposed;
      systemConfigurations = system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          llama_package = llama-cpp.packages.${system}.default;
          llama-cpp-vulkan = llama_package.overrideAttrs (old: {
            useVulkan = true;
            postPatch = '''';
          });
          pythonEnv = pkgs.python3.withPackages (p: [
            p.gradio
            p.openai
            p.e2b-code-interpreter
            p.nbformat
            p.nbconvert
            p.jinja2
          ]);

          ufd = pkgs.stdenv.mkDerivation {
            pname = "united-fisheries-data";
            version = "0.1.0";
            src = ./.;
            buildInputs = with pkgs; [
              vulkan-tools
              pythonEnv
              uv
              llama-cpp-vulkan
            ];
            installPhase = ''
              mkdir -p $out/bin
              PYTHON_EXEC=${pythonEnv}/bin/python
              LLAMA_SERVER_EXEC=${lib.getExe llama-cpp-vulkan}
              # create a startup script
              cat > $out/bin/start-server << EOF
              #!${pkgs.stdenv.shell}

              echo "Starting llama-server backend on port 8080..."

              $LLAMA_SERVER_EXEC \
                -m models/Qwen3-4B-UD-Q8_K_XL.gguf \
                --jinja \
                --reasoning-format deepseek \
                --temp 0.6 \
                --top-p 0.95 \
                --min-p 0 \
                -c 20480 \
                -n 16384 \
                --no-context-shift \
                --chat-template-file src/llama3.jinja \
                --port 8080 & # Explicitly set port
              sleep 5
              echo "Starting gradio frontend on port 7860"
              exec $PYTHON_EXEC -m src.app \
              EOF
              chmod +x $out/bin/start-server
              # 3. Copy necessary runtime files (model, app source)
              cp -r models $out/ 
              cp -r src $out/ 
            '';
          };
          dockerImage = pkgs.dockerTools.buildLayeredImage {
            name = "registry.united-fisheries-data";
            tag = "latest";

            contents = [ pkgs.glibc pkgs.bash ];
            
            config.ExposedPorts = {
              "7860/tcp" = {};
              "8080/tcp" = {};
            };
            config.Cmd = [ "${pkgs.bash}/bin/bash" "-c" ". ${ufd}/bin/start-server" ];
            config.User = "0";
          };
        in
        {
          inherit pkgs ufd llama-cpp-vulkan dockerImage;
        };
      allConfigs = forAllSystems systemConfigurations;

      in
      {
        devShells = forAllSystems (system: {
          default = allConfigs.${system}.pkgs.mkShell {
            packages = [
              allConfigs.${system}.llama-cpp-vulkan
              allConfigs.${system}.pkgs.python3
              allConfigs.${system}.pkgs.uv
              allConfigs.${system}.pkgs.vulkan-tools
            ];
            shellHook = ''
              unset PYTHONPATH
              uv sync
              . .venv/bin/activate
              uv pip install -r requirements.txt --quiet
            '';
          };
        });

        packages = forAllSystems (system: {
          default = allConfigs.${system}.ufd;
          docker = allConfigs.${system}.dockerImage;
        });
      };
  }

