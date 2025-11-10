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
          # llama-cpp-cuda = llama_package.overrideAttrs (old: {
          # })
          pythonEnv = pkgs.python3.withPackages (p: [
            p.ipython
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

              APP_ROOT_PATH="$out"
              # Pre-create destination directories to guarantee they exist
              mkdir -p $out/src

              # This pattern ($src/dir/., $out/dir/) is the most robust copy method.
              cp -r $src/src/. $out/src/
              # ------------------------------------------
              # ls -la $src
              # echo "_________________"
              # ls -la $out
              # create a startup script
              cat > $out/bin/start-server << EOF
              #!${pkgs.stdenv.shell}
              if [ -z "$MODEL_PATH" ]; then
                echo "Error: MODEL_PATH environment variable is not set."
                echo "Please set it to the path of the model file."
                exit 1
              fi

              echo "Starting llama-server backend on port 8080..."

              $LLAMA_SERVER_EXEC \
                -m "$MODEL_PATH" \
                --jinja \
                --reasoning-format deepseek \
                --temp 0.6 \
                --top-p 0.95 \
                --min-p 0 \
                -c 20480 \
                -n 16384 \
                --no-context-shift \
                --chat-template-file $APP_ROOT_PATH/src/llama3.jinja \
                -p 8080 & \
              echo "Starting gradio frontend on port 7860"

              
              exec $PYTHON_EXEC $APP_ROOT_PATH/src/app.py \
              EOF
              chmod +x $out/bin/start-server

            '';
          };
          dockerImage = pkgs.dockerTools.buildLayeredImage {
            name = "united-fisheries-data";
            tag = "latest";

            contents = [ pkgs.glibc pkgs.bash pkgs.coreutils ];
            
            config.ExposedPorts = {
              "7860/tcp" = {};
              "8080/tcp" = {};
            };
            config.Cmd = [ "${pkgs.bash}/bin/bash" "-c" ". ${ufd}/bin/start-server" ];
            config.User = "0";
            config.WorkingDir = "${ufd}";
          };
        in
        {
          inherit pkgs ufd llama-cpp-vulkan dockerImage pythonEnv;
        };
      allConfigs = forAllSystems systemConfigurations;

      in
      {
        devShells = forAllSystems (system: {
          default = allConfigs.${system}.pkgs.mkShell {
            packages = [
              allConfigs.${system}.llama-cpp-vulkan
              allConfigs.${system}.pythonEnv
              allConfigs.${system}.pkgs.uv
              allConfigs.${system}.pkgs.vulkan-tools
              allConfigs.${system}.pkgs.nodejs_22
            ];
            shellHook = ''
              unset PYTHONPATH
              uv sync --upgrade
              . .venv/bin/activate
              uv pip install -r requirements.txt --quiet
              E2B_API_KEY=$(cat key.txt)
              export E2B_API_KEY
              alias npm='nix run .#npm --'
              alias npx='nix run .#npx --'              
            '';
          };
        });

        packages = forAllSystems (system: {
          default = allConfigs.${system}.ufd;
          docker = allConfigs.${system}.dockerImage;
        });
      };
  }

